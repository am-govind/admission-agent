"""Wire schemas for the chat API and the streaming render model.

This is a self-contained render/streaming model (parts + contentBlocks updated via
RFC-6902 JSON Patch). It is intentionally independent of any external platform.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- Chat request ----------
class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str | None = None


class ChatRequest(BaseModel):
    message: str
    conversationId: str | None = None
    history: list[HistoryMessage] = Field(default_factory=list)


# ---------- Render model ----------
class ContentBlock(BaseModel):
    id: str
    type: Literal["text", "table", "image", "code", "chart"]
    data: dict[str, Any]
    annotations: dict[str, Any] | None = None


class RenderState(BaseModel):
    parts: list[dict[str, Any]] = Field(default_factory=list)
    contentBlocks: dict[str, ContentBlock] = Field(default_factory=dict)


# ---------- REST response ----------
class ChatResponse(BaseModel):
    conversationId: str
    messageId: str
    renderState: RenderState
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------- Auth ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
