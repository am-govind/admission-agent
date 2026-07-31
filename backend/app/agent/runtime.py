"""Turn orchestration: guardrails -> memory -> router -> loop -> render blocks.

Tables and charts are emitted as native content blocks rather than as markdown inside
the reply, so the frontend renders a real table and a real chart, and the model is not
asked to format data it might reformat incorrectly.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from ..analytics import series
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
    plotted = [c for c in spec.y if c in columns and c != spec.x]
    if not plotted or len(result.rows) < 2:
        return None

    index = {name: i for i, name in enumerate(columns)}
    rows: list[dict] = []
    for row in result.rows:
        # Subtotal and grand-total rows would dwarf every real bar.
        label = str(row[index[spec.x]])
        if label.lower() in series.TOTAL_LABELS:
            continue
        rows.append({spec.x: jsonable(row[index[spec.x]]),
                     **{c: jsonable(row[index[c]]) for c in plotted}})
    if len(rows) < 2:
        return None

    return ContentBlock(
        id=f"chart-{uuid.uuid4().hex[:8]}",
        type="chart",
        data={"kind": spec.to_dict()["kind"], "x": spec.x, "y": plotted,
              "title": spec.title, "rows": rows},
    )


def _single_series(result: ToolResult) -> bool:
    """One x column and one value column — the shape that can join a comparison."""
    return result.chart is not None and len(result.columns) == 2


def _group_key(result: ToolResult, position: int) -> tuple:
    """Results that measure the same thing on the same axis share a key.

    Anything not single-series shaped gets a key unique to its position, so it passes
    through on its own and can never be folded into someone else's chart.
    """
    if not _single_series(result) or result.chart is None:
        return ("solo", position)
    return (result.metric, result.chart.x, result.chart.kind)


def _blocks(results: list[ToolResult]) -> tuple[list[ContentBlock], list[str]]:
    """Content blocks plus provenance lines, merging comparable series into one chart.

    A model asked for "Maharashtra vs South" may call one tool twice rather than using
    the compare parameter. Two charts answer that question worse than one, so results
    measuring the same metric on the same axis are pivoted together here as well. Each
    series keeps its own provenance line, so merging never hides where a number came
    from.
    """
    provenance: list[str] = []
    for result in results:
        if result.provenance is not None:
            description = result.provenance.describe()
            if description not in provenance:
                provenance.append(description)

    # The same tool called twice in a turn must not render the same table twice.
    unique: list[ToolResult] = []
    seen: set[str] = set()
    for result in results:
        if not result.has_table:
            continue
        fingerprint = json.dumps(
            [result.metric, result.columns, result.table_payload()["rows"]],
            ensure_ascii=False, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(result)

    groups: dict[tuple, list[ToolResult]] = {}
    for position, result in enumerate(unique):
        groups.setdefault(_group_key(result, position), []).append(result)

    blocks: list[ContentBlock] = []
    for group in groups.values():
        merged = series.merge(group) if len(group) > 1 else None
        for item in ([merged] if merged is not None else group):
            chart = _chart_block(item)
            if chart is not None:
                blocks.append(chart)
            blocks.append(_table_block(item))
    return blocks, provenance


async def run_turn(message: str, conversation_id: str | None = None,
                   history: list[dict] | None = None,
                   progress: Progress | None = None) -> TurnResult:
    """Route the message to one skill, run its tools, and assemble the reply."""
    started = time.perf_counter()
    slots = memory.load(conversation_id) if conversation_id else {}
    log.info("Turn starting: %.200s", message)
    if slots:
        log.debug("Memory in scope: %s", slots)

    if progress:
        progress("Choosing the right skill...")
    route = await router.route(message, history)
    log.info("Routed to %s via %s (%s)", route.skill_id, route.method, route.reason)

    outcome = await loop.run_loop(
        message=message, skill=route.skill, history=history, slots=slots,
        conversation_id=conversation_id, progress=progress)

    blocks, provenance = _blocks(outcome.rendered_results)
    declined = [r.metric for r in outcome.results if not r.ok]
    if declined:
        log.info("Declined in this turn: %s", ", ".join(declined))

    text = outcome.text
    if not text:
        log.warning("The model returned no text after %s tool call(s)",
                    len(outcome.tool_calls))
        text = ("I could not produce an answer for that. Try rephrasing, or ask for a "
                "specific metric such as registrations, 2nd EMI collection or ARPU.")
    note = availability.staleness_note()
    if note:
        log.warning("Serving with a staleness warning: %s", note)
        text = f"{note}\n\n{text}"

    if conversation_id:
        await memory.update_summary(conversation_id)

    log.info("Turn done in %.0fms: skill=%s tools=[%s] blocks=%s chars=%s",
             (time.perf_counter() - started) * 1000, route.skill_id,
             ", ".join(outcome.tool_calls), len(blocks), len(text))

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
