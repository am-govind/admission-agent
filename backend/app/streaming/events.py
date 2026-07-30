"""SSE event frame builders for the self-contained streaming protocol.

Frame format:  event: <name>\\n data: <json>\\n\\n
The render model is (parts[], contentBlocks{}) updated via RFC-6902 JSON Patch
carried on `state-delta` events. Text streams via text-message-* events.
"""
from __future__ import annotations

import json
import time
from typing import Any


def _frame(event: str, payload: dict[str, Any]) -> str:
    payload = {"type": event, "timestamp": int(time.time() * 1000), **payload}
    return f"event: {event.replace('-', '_')}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def run_started(thread_id: str, run_id: str, conversation_id: str, message_id: str) -> str:
    return _frame("run-started", {"threadId": thread_id, "runId": run_id,
                                  "conversationId": conversation_id, "messageId": message_id})


def thinking_start() -> str:
    return _frame("thinking-start", {})


def thinking_end() -> str:
    return _frame("thinking-end", {})


def processing_status(message: str) -> str:
    return _frame("processing-status", {"message": message})


def text_message_start(part_id: str) -> str:
    return _frame("text-message-start", {"partId": part_id, "role": "assistant"})


def text_message_content(part_id: str, delta: str) -> str:
    return _frame("text-message-content", {"partId": part_id, "delta": delta})


def text_message_end(part_id: str) -> str:
    return _frame("text-message-end", {"partId": part_id})


def state_delta(delta: list[dict[str, Any]]) -> str:
    return _frame("state-delta", {"delta": delta})


def add_block(block: dict[str, Any]) -> str:
    """Convenience: JSON-Patch to add a content block AND a block-ref part."""
    return state_delta([
        {"op": "add", "path": f"/contentBlocks/{block['id']}", "value": block},
        {"op": "add", "path": "/parts/-", "value": {"type": "block-ref", "id": block["id"]}},
    ])


def run_finished(thread_id: str, run_id: str, metadata: dict[str, Any] | None = None) -> str:
    return _frame("run-finished", {"threadId": thread_id, "runId": run_id,
                                   "metadata": metadata or {}})


def run_error(thread_id: str, run_id: str, code: str, message: str) -> str:
    return _frame("run-error", {"threadId": thread_id, "runId": run_id,
                                "error": {"code": code, "message": message}})
