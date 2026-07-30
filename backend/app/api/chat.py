"""Chat routes — streaming (SSE) and REST."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..agent.runtime import run_turn
from ..core.security import current_user
from ..data import conversation
from ..guardrails import GuardrailError, scan_input, scan_output
from ..models import ChatRequest, ChatResponse, RenderState
from ..streaming.sse import stream_turn

router = APIRouter(tags=["chat"])


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, user: str = Depends(current_user)):
    cid = conversation.ensure_conversation(body.conversationId, user)

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

    cid = conversation.ensure_conversation(body.conversationId, user)
    turn = conversation.next_turn(cid)
    conversation.add_message(cid, turn, "user", body.message)
    history = conversation.get_history(cid)
    try:
        output = await run_turn(body.message, history)
    except Exception as e:  # noqa: BLE001 - surface a clean error to the client
        raise HTTPException(
            status_code=503, detail=f"The model service is unavailable: {e}") from e

    answer = scan_output(output.text)
    state = RenderState()
    part_id = f"text-{uuid.uuid4().hex[:8]}"
    state.parts.append({"type": "text", "id": part_id, "content": answer})
    for block in output.artifacts:
        state.contentBlocks[block.id] = block
        state.parts.append({"type": "block-ref", "id": block.id})
    if output.provenance:
        prov = "How I got this: " + " | ".join(dict.fromkeys(output.provenance))
        state.parts.append({"type": "text", "id": f"text-{uuid.uuid4().hex[:8]}", "content": prov})
        answer = f"{answer}\n\n{prov}"

    conversation.add_message(cid, turn, "assistant", answer)
    return ChatResponse(
        conversationId=cid, messageId=f"msg-{uuid.uuid4().hex[:10]}", renderState=state,
        metadata={"turnId": turn, "skill": output.skill_id, "routeReason": output.route_reason})
