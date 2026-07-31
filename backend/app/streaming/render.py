"""Assembles one answer into a RenderState.

Both the SSE path and the REST path need the same object: the streaming path emits it
as JSON Patch frames and persists the result, the REST path returns it directly. Keeping
the assembly in one place is what makes a reloaded conversation identical to the live one.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ..models import RenderState

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    from ..agent.runtime import TurnResult


def provenance_line(provenance: list[str]) -> str:
    """The footnote shown under an answer, or "" when there is nothing to cite."""
    if not provenance:
        return ""
    return "How I got this: " + " | ".join(dict.fromkeys(provenance))


def build_render_state(
    output: "TurnResult",
    answer: str,
    text_part_id: str | None = None,
    provenance_part_id: str | None = None,
) -> tuple[RenderState, str]:
    """Return the render state for one answer plus the text to persist for the LLM.

    Blocks come first so the table or chart renders above the prose. `text_part_id` and
    `provenance_part_id` let the streaming path reuse the ids it already put on the wire.
    """
    state = RenderState()
    for block in output.artifacts:
        state.contentBlocks[block.id] = block
        state.parts.append({"type": "block-ref", "id": block.id})

    state.parts.append({
        "type": "text",
        "id": text_part_id or f"text-{uuid.uuid4().hex[:8]}",
        "content": answer,
    })

    stored = answer
    provenance = provenance_line(output.provenance)
    if provenance:
        state.parts.append({
            "type": "text",
            "id": provenance_part_id or f"text-{uuid.uuid4().hex[:8]}",
            "content": provenance,
        })
        stored = f"{answer}\n\n{provenance}"
    return state, stored
