"""Chat routes — streaming (SSE) and REST."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..agent.llm import LlmUnavailable
from ..agent.memory import history_for_prompt
from ..agent.runtime import run_turn
from ..core.logs import bind_conversation
from ..core.security import current_user
from ..data import conversation
from ..guardrails import GuardrailError, scan_input, scan_output
from ..models import ChatRequest, ChatResponse
from ..streaming.render import build_render_state
from ..streaming.sse import stream_turn

router = APIRouter(tags=["chat"])


def _resolve_conversation(conversation_id: str | None, user: str) -> str:
    try:
        return conversation.ensure_conversation(conversation_id, user)
    except conversation.NotOwned as e:
        raise HTTPException(status_code=404, detail="Conversation not found") from e


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, user: str = Depends(current_user)):
    cid = _resolve_conversation(body.conversationId, user)

    async def gen():
        async for frame in stream_turn(body.message, cid):
            yield frame

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
                 "X-Conversation-Id": cid},
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: str = Depends(current_user)) -> ChatResponse:
    try:
        scan_input(body.message)
    except GuardrailError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    cid = _resolve_conversation(body.conversationId, user)
    bind_conversation(cid)
    turn = conversation.next_turn(cid)
    conversation.add_message(cid, turn, "user", body.message)
    conversation.set_title_if_missing(cid, body.message)
    history = history_for_prompt(cid)
    try:
        output = await run_turn(body.message, cid, history)
    except LlmUnavailable as e:
        # 429 rather than 503 for a quota, so a client can tell "come back later" from
        # "the service is broken" without parsing the message.
        raise HTTPException(
            status_code=429 if e.quota_exhausted else 503,
            detail=e.user_message()) from e
    except Exception as e:  # noqa: BLE001 - surface a clean error to the client
        raise HTTPException(
            status_code=503, detail=f"The model service is unavailable: {e}") from e

    answer = scan_output(output.text)
    state, stored = build_render_state(output, answer)

    conversation.add_message(cid, turn, "assistant", stored, state.model_dump())
    return ChatResponse(
        conversationId=cid, messageId=f"msg-{uuid.uuid4().hex[:10]}", renderState=state,
        metadata={"turnId": turn, "skill": output.skill_id,
                  "skillName": output.skill_name, "routeReason": output.route_reason,
                  "routeMethod": output.route_method, "toolCalls": output.tool_calls})
