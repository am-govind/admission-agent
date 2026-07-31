"""Tool registration and the LLM-facing schema.

A tool is a name, a description, a pydantic parameter model and a one-line function
that delegates to analytics. The parameter model is the boundary: arguments are
validated here, before any SQL runs, so a hallucinated argument produces a corrective
message to the model rather than a stack trace or a wrong number.

Business logic must not live in this package — see analytics/filters.py for why.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Sequence, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...analytics.result import ToolResult
# Imported so the advertised class names cannot drift from the ones analytics accepts.
from ...data.schema import CLASSWISE_TOKENS

log = logging.getLogger(__name__)


def _collapse_optional(schema: dict[str, Any]) -> dict[str, Any]:
    """Turn pydantic's `anyOf: [{type: x}, {type: null}]` into `type: x`.

    Optionality is already expressed by omission from `required`, and some providers
    handle the flattened form more reliably.
    """
    variants = schema.get("anyOf")
    if not variants:
        return schema
    concrete = [v for v in variants if v.get("type") != "null"]
    if len(concrete) != 1:
        return schema
    merged = {k: v for k, v in schema.items() if k != "anyOf"}
    merged.update(concrete[0])
    return merged


def _clean(schema: dict[str, Any]) -> dict[str, Any]:
    properties = {}
    for name, prop in (schema.get("properties") or {}).items():
        cleaned = _collapse_optional(dict(prop))
        cleaned.pop("title", None)
        cleaned.pop("default", None)
        properties[name] = cleaned
    return {
        "type": "object",
        "properties": properties,
        "required": list(schema.get("required") or []),
        "additionalProperties": False,
    }


@dataclass
class Tool:
    name: str
    description: str
    params_model: Type[BaseModel]
    fn: Callable[..., ToolResult]

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean(self.params_model.model_json_schema()),
            },
        }

    def run(self, raw_args: dict[str, Any] | None = None) -> ToolResult:
        """Validate arguments, then delegate. Never raises."""
        try:
            params = self.params_model.model_validate(raw_args or {})
        except ValidationError as e:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'argument'}: {err['msg']}"
                for err in e.errors())
            return ToolResult.unavailable(
                self.name, f"the arguments were not valid ({problems}). Correct them and "
                           "call the tool again")
        try:
            return self.fn(**params.model_dump())
        except Exception as e:  # noqa: BLE001 - one failing tool must not end the turn
            log.exception("Tool %s failed", self.name)
            return ToolResult.unavailable(
                self.name, f"the {self.name} calculation failed unexpectedly "
                           f"({type(e).__name__})")


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, params: Type[BaseModel]):
    """Register a function as an agent-callable tool."""
    def decorator(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        if name in REGISTRY:
            raise ValueError(f"Tool {name!r} is already registered")
        REGISTRY[name] = Tool(name=name, description=description, params_model=params, fn=fn)
        return fn
    return decorator


def get_tool(name: str) -> Tool | None:
    return REGISTRY.get(name)


def schemas_for(names: Sequence[str]) -> list[dict[str, Any]]:
    """OpenAI function schemas for the named tools, skipping any that do not exist."""
    return [REGISTRY[n].openai_schema() for n in names if n in REGISTRY]


def all_names() -> list[str]:
    return sorted(REGISTRY)


# ---------- shared parameter models ----------

class Params(BaseModel):
    """Base for every tool's parameter model.

    `extra="forbid"` makes the advertised `additionalProperties: false` true: a
    hallucinated argument such as `centre` must come back as a corrective message. The
    pydantic default of silently dropping it would answer a center-specific question
    with whole-organisation numbers.
    """
    model_config = ConfigDict(extra="forbid")


class NoParams(Params):
    pass


class ScopeParams(Params):
    center: str | None = Field(
        None, description="Center name or a distinctive part of it, e.g. 'Panvel' or "
                          "'Mumbai - Panvel Vidyapeeth'. Omit for the whole organisation.")
    region: str | None = Field(
        None, description="Region name: 'Maharashtra', 'AP & TS' or 'South'. Omit for "
                          "the whole organisation.")


# The admissions family accepts exclusion and class filters on top of the shared scope.
# They are declared here rather than on ScopeParams because the finance and retention
# tools share that base and their analytics functions take neither argument — a widened
# base would hand them a keyword they cannot accept.

_CLASS_LABELS = ", ".join(label for label, _ in CLASSWISE_TOKENS)


class AdmissionsScopeParams(ScopeParams):
    exclude: str | None = Field(
        None, description="Subtract a center, city or region from the scope. Use for "
                          "'rest of' and 'excluding' questions: region='Maharashtra' with "
                          "exclude='Mumbai' means the Maharashtra centers outside Mumbai.")


class AdmissionsFilterParams(AdmissionsScopeParams):
    classes: list[str] | None = Field(
        None, description=f"Filter to specific classes, e.g. ['Dropper JEE', "
                          f"'Dropper NEET']. Valid values: {_CLASS_LABELS}. "
                          f"Omit to count every class.")


class AdmissionsCompareParams(AdmissionsFilterParams):
    compare: list[str] | None = Field(
        None, description="Two to five centers, cities or regions to chart together, "
                          "e.g. ['Maharashtra', 'South'] or ['Pune', 'Nagpur']. One call "
                          "with compare produces a single chart with one line per scope, "
                          "which is far more readable than calling this tool once per "
                          "scope. Overrides center and region when set.")


class AdmissionsDailyParams(AdmissionsCompareParams):
    days: int = Field(20, ge=1, le=90, description="How many days back to report.")


class AdmissionsTrendParams(AdmissionsCompareParams):
    months: int = Field(12, ge=1, le=36, description="How many months back to report.")


class AdmissionsMonthlyParams(AdmissionsFilterParams):
    months_back: int = Field(
        0, ge=0, le=36,
        description="0 for the current month, 1 for last month, 2 for the month before "
                    "that, and so on. Counted from the data's reference date.")


class RegionParams(Params):
    region: str | None = Field(
        None, description="Restrict to one region. Omit to cover every center.")


class RegionLimitParams(RegionParams):
    limit: int = Field(15, ge=1, le=53, description="How many centers to return.")


class LimitParams(Params):
    limit: int = Field(10, ge=1, le=53, description="How many rows to return.")


class TableParams(Params):
    table: str = Field(
        ..., description="One of: rd26, rd25, finance_dump, targets.")


class MetricParams(Params):
    metric: str = Field(
        "registrations",
        description="Metric to roll up: registrations, monthly_admissions, first_emi, "
                    "autopay, second_emi, senior_retention, cancellations, arpu.")


class MetricRegionParams(MetricParams):
    region: str | None = Field(
        None, description="Restrict to one region. Omit to cover every center.")


class ExploreParams(Params):
    sql: str = Field(
        ..., description="A single read-only DuckDB SELECT (or WITH ... SELECT). Tables: "
                         "rd26, rd25, finance_dump, targets. Columns holding personal "
                         "data (student_name, regno) cannot be referenced. Always alias "
                         "computed columns to readable names.")
    limit: int | None = Field(
        None, ge=1, description="Row cap; the server applies its own maximum as well.")
