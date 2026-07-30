"""The single shape every analytics function returns.

One envelope for every outcome — a number, a table, a decline, a clarifying question —
means the tool layer, the render layer and the LLM all handle results identically, and
that no code path can produce a figure without provenance attached to it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

CHART_KINDS = ("bar", "line", "area", "pie")

# Rows beyond this are withheld from the model's copy of the result. The full set
# still goes to the frontend table block; the model only needs enough to describe it.
MAX_MODEL_ROWS = 40


@dataclass
class Provenance:
    """How a figure was produced, so an answer can always be audited."""

    metric: str
    source_tables: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    reference_date: str | None = None
    scope: str | None = None
    row_count: int | None = None
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        parts = [f"metric {self.metric}"]
        if self.scope:
            parts.append(f"scope {self.scope}")
        if self.source_tables:
            parts.append("from " + ", ".join(self.source_tables))
        if self.filters:
            parts.append("filters " + " AND ".join(self.filters))
        if self.reference_date:
            parts.append(f"as of {self.reference_date}")
        if self.notes:
            parts.extend(self.notes)
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "sourceTables": self.source_tables,
            "filters": self.filters,
            "referenceDate": self.reference_date,
            "scope": self.scope,
            "rowCount": self.row_count,
            "notes": self.notes,
            "description": self.describe(),
        }


@dataclass
class ChartSpec:
    kind: Literal["bar", "line", "area", "pie"]
    x: str
    y: list[str]
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind if self.kind in CHART_KINDS else "bar"
        return {"kind": kind, "x": self.x, "y": list(self.y), "title": self.title}


def jsonable(value: Any) -> Any:
    """DuckDB returns Decimal and date objects that json.dumps cannot serialise."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()[:10]
    if isinstance(value, (int, float)):
        return value
    return str(value)


@dataclass
class ToolResult:
    """Outcome of one analytics call.

    Exactly one of these states holds:
      ok=True                       -> values / rows carry the answer
      unavailable_reason is set     -> the source data cannot support the question
      clarification is set          -> the scope was ambiguous and must be narrowed
    """

    metric: str
    ok: bool = True
    summary: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    chart: ChartSpec | None = None
    provenance: Provenance | None = None
    unavailable_reason: str | None = None
    clarification: str | None = None
    candidates: list[str] = field(default_factory=list)

    # ---------- constructors for the non-happy paths ----------
    @classmethod
    def unavailable(cls, metric: str, reason: str) -> "ToolResult":
        return cls(
            metric=metric, ok=False, unavailable_reason=reason,
            summary=f"I cannot answer that from the current data: {reason}.")

    @classmethod
    def needs_clarification(cls, metric: str, question: str,
                            candidates: list[str] | None = None) -> "ToolResult":
        return cls(metric=metric, ok=False, clarification=question,
                   candidates=candidates or [], summary=question)

    # ---------- views ----------
    @property
    def has_table(self) -> bool:
        return bool(self.columns and self.rows)

    def decline_reason(self) -> str:
        """Why this result is not ok, as one string, for logs and assertion messages.

        Callers otherwise have to remember which of the two mutually exclusive fields
        was set, and a wrong guess produces a misleading empty message.
        """
        if self.ok:
            return ""
        return self.unavailable_reason or self.clarification or "no reason given"

    def table_payload(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "rows": [[jsonable(v) for v in row] for row in self.rows],
        }

    def to_model_payload(self) -> dict[str, Any]:
        """The compact form handed back to the LLM as the tool's output.

        Row-heavy results are truncated here so a 53-center breakdown cannot crowd
        out the conversation; the untruncated rows still reach the frontend.
        """
        payload: dict[str, Any] = {"metric": self.metric, "ok": self.ok}
        if self.unavailable_reason:
            payload["unavailable_reason"] = self.unavailable_reason
            payload["instruction"] = (
                "Tell the user this figure is unavailable and give the reason. "
                "Do not estimate, infer, or substitute another metric.")
            return payload
        if self.clarification:
            payload["clarification_needed"] = self.clarification
            if self.candidates:
                payload["candidates"] = self.candidates
            payload["instruction"] = "Ask the user this question before computing anything."
            return payload

        if self.summary:
            payload["summary"] = self.summary
        if self.values:
            payload["values"] = {k: jsonable(v) for k, v in self.values.items()}
        if self.has_table:
            shown = self.rows[:MAX_MODEL_ROWS]
            payload["columns"] = list(self.columns)
            payload["rows"] = [[jsonable(v) for v in row] for row in shown]
            if len(self.rows) > len(shown):
                payload["rows_truncated"] = (
                    f"showing {len(shown)} of {len(self.rows)} rows; the full table is "
                    "already displayed to the user")
        if self.provenance:
            payload["provenance"] = self.provenance.describe()
        return payload
