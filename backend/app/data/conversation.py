"""Conversation store — backend is the source of truth for history."""
from __future__ import annotations

import uuid

from ..core.database import _lock, execute, get_conn


def new_conversation(username: str) -> str:
    cid = f"conv-{uuid.uuid4().hex[:12]}"
    conn = get_conn()
    with _lock:
        conn.execute("INSERT INTO conversations (conversation_id, username) VALUES (?, ?)",
                     [cid, username])
    return cid


def ensure_conversation(conversation_id: str | None, username: str) -> str:
    if not conversation_id:
        return new_conversation(username)
    rows = execute("SELECT 1 FROM conversations WHERE conversation_id = ?", [conversation_id])
    if not rows:
        conn = get_conn()
        with _lock:
            conn.execute("INSERT INTO conversations (conversation_id, username) VALUES (?, ?)",
                         [conversation_id, username])
    return conversation_id


def next_turn(conversation_id: str) -> int:
    rows = execute("SELECT COALESCE(MAX(turn_id), 0) FROM messages WHERE conversation_id = ?",
                   [conversation_id])
    return int(rows[0][0]) + 1


def add_message(conversation_id: str, turn_id: int, role: str, content: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO messages (conversation_id, turn_id, role, content) VALUES (?, ?, ?, ?)",
            [conversation_id, turn_id, role, content])


def get_history(conversation_id: str, limit: int = 20) -> list[dict]:
    rows = execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? "
        "ORDER BY turn_id DESC, created_at DESC LIMIT ?", [conversation_id, limit])
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
