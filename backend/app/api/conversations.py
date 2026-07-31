"""Conversation history routes — list, open, rename, delete."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.security import current_user
from ..data import conversation

router = APIRouter(tags=["conversations"])


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def _owned(conversation_id: str, user: str) -> None:
    """404 rather than 403: an id the caller does not own should not be confirmable."""
    if not conversation.owns(conversation_id, user):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/conversations")
def list_conversations(user: str = Depends(current_user)) -> dict:
    return {"conversations": conversation.list_for_user(user)}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: str = Depends(current_user)) -> dict:
    _owned(conversation_id, user)
    meta = conversation.get_meta(conversation_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {**meta, "messages": conversation.get_transcript(conversation_id)}


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: RenameRequest,
                        user: str = Depends(current_user)) -> dict:
    _owned(conversation_id, user)
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be blank")
    conversation.set_title(conversation_id, title)
    return {"conversationId": conversation_id, "title": title}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: str = Depends(current_user)) -> dict:
    _owned(conversation_id, user)
    conversation.delete(conversation_id)
    return {"deleted": conversation_id}
