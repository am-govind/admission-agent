"""Orchestrates one chat turn into an SSE event stream."""
from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

from ..agent.runtime import run_turn
from ..data.conversation import add_message, get_history, next_turn
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
    history = get_history(conversation_id)

    yield events.processing_status("Writing SQL query...")

    try:
        output = await run_turn(message, history)
    except Exception as e:
        yield events.thinking_end()
        yield events.run_error(thread_id, run_id, "AGENT_ERROR", f"Service unavailable: {e}")
        return

    try:
        scan_output(output.text)
    except GuardrailError as e:
        yield events.thinking_end()
        yield events.run_error(thread_id, run_id, "OUTPUT_BLOCKED", str(e))
        return

    yield events.thinking_end()

    # Charts go above the table so the visual lands first.
    for block in output.artifacts:
        yield events.add_block(block.model_dump())

    # Stream text chunks
    part_id = f"part-{uuid.uuid4().hex[:10]}"
    yield events.text_message_start(part_id)
    for chunk in _chunk(output.text):
        yield events.text_message_content(part_id, chunk)
        await asyncio.sleep(0.02)
    yield events.text_message_end(part_id)

    add_message(conversation_id, turn, "assistant", output.text)
    yield events.run_finished(thread_id, run_id)
