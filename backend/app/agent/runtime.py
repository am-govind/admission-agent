"""Turn orchestration for Text-to-SQL agent."""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from ..models import ContentBlock
from ..core.database import execute_dicts

log = logging.getLogger(__name__)

_CHART_KINDS = {"bar", "line", "area", "pie"}
_MAX_CHART_ROWS = 50

@dataclass
class TurnResult:
    text: str
    skill_id: str = "sql_agent"
    skill_name: str = "Text-to-SQL"
    route_reason: str = "Unified Agent"
    artifacts: list[ContentBlock] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)

def _with_history(message: str, history: list[dict] | None) -> str:
    if history:
        hist = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])
        return f"[Recent conversation]\n{hist}\n\n[User]\n{message}"
    return message

def _to_markdown_table(cols: list[str], rows: list[dict]) -> str:
    if not rows: return "No results found."
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows)
    return f"{header}\n{sep}\n{body}"

def _is_number(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)

def _jsonable(v):
    """DuckDB hands back Decimal/date objects that json.dumps cannot serialize."""
    if v is None: return None  # Recharts renders null as a gap rather than a zero.
    if isinstance(v, Decimal): return float(v)
    return v if _is_number(v) else str(v)

def _chart_block(cols: list[str], rows: list[dict], spec: dict | None) -> ContentBlock | None:
    """Chart the result set, honouring the model's spec when it names real columns."""
    if len(cols) < 2 or not 1 < len(rows) <= _MAX_CHART_ROWS:
        return None
    numeric = [c for c in cols
               if (vals := [r[c] for r in rows if r.get(c) is not None]) and all(map(_is_number, vals))]
    spec = spec if isinstance(spec, dict) else {}
    x = spec.get("x") if spec.get("x") in cols else next((c for c in cols if c not in numeric), None)
    wanted = spec.get("y") or []
    wanted = [wanted] if isinstance(wanted, str) else wanted
    # x is excluded from y so a numeric x-axis (e.g. month number) is not also drawn as a series.
    y = [c for c in wanted if c in numeric and c != x] or [c for c in numeric if c != x]
    if not x or not y:
        return None
    return ContentBlock(
        id=f"chart-{uuid.uuid4().hex[:8]}",
        type="chart",
        data={
            "kind": spec.get("kind") if spec.get("kind") in _CHART_KINDS else "bar",
            "x": x, "y": y, "title": str(spec.get("title") or ""),
            "rows": [{c: _jsonable(r.get(c)) for c in [x, *y]} for r in rows],
        },
    )

async def run_turn(message: str, history: list[dict] | None = None) -> TurnResult:
    from .sql_agent import run_sql_agent

    response = await run_sql_agent(_with_history(message, history))
    if not response.sql_query:
        return TurnResult(text="Sorry, I couldn't understand the model's response format.")

    try:
        cols, rows = execute_dicts(response.sql_query)
    except Exception as e:
        log.error(f"SQL error: {e}\nQuery: {response.sql_query}\nThought: {response.thought_process}")
        return TurnResult(text="Sorry, I couldn't process that question. Please try rephrasing it.")

    chart = _chart_block(cols, rows, response.chart)
    return TurnResult(text=_to_markdown_table(cols, rows), artifacts=[chart] if chart else [])
