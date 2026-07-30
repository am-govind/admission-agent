"""Turn orchestration: guardrails -> memory -> router -> loop -> render blocks.

Tables and charts are emitted as native content blocks rather than as markdown inside
the reply, so the frontend renders a real table and a real chart, and the model is not
asked to format data it might reformat incorrectly.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from ..analytics.result import ToolResult, jsonable
from ..data import availability
from ..models import ContentBlock
from . import loop, memory, router
from .loop import Progress

log = logging.getLogger(__name__)


@dataclass
class TurnResult:
    text: str
    skill_id: str = "knowledge"
    skill_name: str = "Knowledge"
    route_reason: str = ""
    route_method: str = "keyword"
    artifacts: list[ContentBlock] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)


def _table_block(result: ToolResult) -> ContentBlock:
    payload = result.table_payload()
    return ContentBlock(
        id=f"table-{uuid.uuid4().hex[:8]}",
        type="table",
        data={"columns": payload["columns"], "rows": payload["rows"],
              "title": result.chart.title if result.chart else ""},
    )


def _chart_block(result: ToolResult) -> ContentBlock | None:
    """Chart the result when the spec names real columns and there is enough to plot."""
    spec = result.chart
    if spec is None or not result.rows:
        return None
    columns = list(result.columns)
    if spec.x not in columns:
        return None
    series = [c for c in spec.y if c in columns and c != spec.x]
    if not series or len(result.rows) < 2:
        return None

    index = {name: i for i, name in enumerate(columns)}
    rows: list[dict] = []
    for row in result.rows:
        # Subtotal and grand-total rows would dwarf every real bar.
        label = str(row[index[spec.x]])
        if label.lower() in {"grand total", "subtotal", "total"}:
            continue
        rows.append({spec.x: jsonable(row[index[spec.x]]),
                     **{c: jsonable(row[index[c]]) for c in series}})
    if len(rows) < 2:
        return None

    return ContentBlock(
        id=f"chart-{uuid.uuid4().hex[:8]}",
        type="chart",
        data={"kind": spec.to_dict()["kind"], "x": spec.x, "y": series,
              "title": spec.title, "rows": rows},
    )


def _blocks(results: list[ToolResult]) -> tuple[list[ContentBlock], list[str]]:
    blocks: list[ContentBlock] = []
    provenance: list[str] = []
    seen: set[str] = set()

    for result in results:
        if result.provenance is not None:
            description = result.provenance.describe()
            if description not in provenance:
                provenance.append(description)
        if not result.has_table:
            continue
        # The same tool called twice in a turn must not render the same table twice.
        fingerprint = json.dumps(
            [result.metric, result.columns, result.table_payload()["rows"]],
            ensure_ascii=False, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        chart = _chart_block(result)
        if chart is not None:
            blocks.append(chart)
        blocks.append(_table_block(result))
    return blocks, provenance


async def run_turn(message: str, conversation_id: str | None = None,
                   history: list[dict] | None = None,
                   progress: Progress | None = None) -> TurnResult:
    """Route the message to one skill, run its tools, and assemble the reply."""
    slots = memory.load(conversation_id) if conversation_id else {}

    if progress:
        progress("Choosing the right skill...")
    route = await router.route(message, history)
    log.info("Routed to %s via %s (%s)", route.skill_id, route.method, route.reason)

    outcome = await loop.run_loop(
        message=message, skill=route.skill, history=history, slots=slots,
        conversation_id=conversation_id, progress=progress)

    blocks, provenance = _blocks(outcome.rendered_results)

    text = outcome.text or (
        "I could not produce an answer for that. Try rephrasing, or ask for a specific "
        "metric such as registrations, 2nd EMI collection or ARPU.")
    note = availability.staleness_note()
    if note:
        text = f"{note}\n\n{text}"

    if conversation_id:
        await memory.update_summary(conversation_id)

    return TurnResult(
        text=text,
        skill_id=route.skill_id,
        skill_name=route.skill.name,
        route_reason=route.reason,
        route_method=route.method,
        artifacts=blocks,
        provenance=provenance,
        tool_calls=outcome.tool_calls,
    )
