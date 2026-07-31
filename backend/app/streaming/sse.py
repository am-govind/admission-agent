"""Orchestrates one chat turn into an SSE event stream."""
from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from typing import AsyncIterator

from ..agent.llm import LlmUnavailable
from ..agent.memory import history_for_prompt
from ..agent.runtime import run_turn
from ..core.logs import bind_conversation
from ..data.conversation import add_message, next_turn
from ..guardrails import GuardrailError, scan_input, scan_output
from . import events


def _chunk(text: str, size: int = 3) -> list[str]:
    words = text.split(" ")
    return [" ".join(words[i:i + size]) + (" " if i + size < len(words) else "")
            for i in range(0, len(words), size)]


async def stream_turn(message: str, conversation_id: str) -> AsyncIterator[str]:
    thread_id = conversation_id
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    message_id = f"msg-{uuid.uuid4().hex[:10]}"
    bind_conversation(conversation_id)

    yield events.run_started(thread_id, run_id, conversation_id, message_id)
    yield events.thinking_start()

    try:
        scan_input(message)
    except GuardrailError as e:
        yield events.thinking_end()
        yield events.run_error(thread_id, run_id, "INPUT_BLOCKED", str(e))
        return

    turn = next_turn(conversation_id)
    add_message(conversation_id, turn, "user", message)
    history = history_for_prompt(conversation_id)

    # The turn reports progress through a queue so each tool call can be surfaced while
    # the turn is still running, without run_turn needing to be a generator.
    updates: asyncio.Queue[str] = asyncio.Queue()
    task = asyncio.create_task(
        run_turn(message, conversation_id, history, progress=updates.put_nowait))

    while not task.done():
        try:
            status = await asyncio.wait_for(updates.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        yield events.processing_status(status)
    while not updates.empty():
        yield events.processing_status(updates.get_nowait())

    try:
        output = task.result()
    except LlmUnavailable as e:
        # Reached only when no tool result survived either; the loop answers from
        # partial results whenever it can. The chain detail belongs in the log, not
        # in the user's chat window.
        logging.getLogger(__name__).error("Model unavailable for the whole turn: %s", e)
        yield events.thinking_end()
        yield events.run_error(
            thread_id, run_id,
            "QUOTA_EXHAUSTED" if e.quota_exhausted else "MODEL_UNAVAILABLE",
            e.user_message())
        return
    except Exception as e:  # noqa: BLE001 - the client needs one clean error frame
        logging.getLogger(__name__).error("Turn crashed:\n%s", traceback.format_exc())
        yield events.thinking_end()
        yield events.run_error(thread_id, run_id, "AGENT_ERROR", f"Service unavailable: {e}")
        return

    # scan_output returns the masked text; using the return value is the whole point.
    answer = scan_output(output.text)

    yield events.thinking_end()

    # Charts and tables first so the visual lands before the prose.
    for block in output.artifacts:
        yield events.add_block(block.model_dump())

    part_id = f"part-{uuid.uuid4().hex[:10]}"
    yield events.text_message_start(part_id)
    for chunk in _chunk(answer):
        yield events.text_message_content(part_id, chunk)
        await asyncio.sleep(0.02)
    yield events.text_message_end(part_id)

    stored = answer
    if output.provenance:
        provenance = "How I got this: " + " | ".join(dict.fromkeys(output.provenance))
        yield events.add_text_part(provenance)
        stored = f"{answer}\n\n{provenance}"

    add_message(conversation_id, turn, "assistant", stored)
    yield events.run_finished(thread_id, run_id, {
        "skill": output.skill_id, "skillName": output.skill_name,
        "routeReason": output.route_reason, "routeMethod": output.route_method,
        "toolCalls": output.tool_calls,
    })
