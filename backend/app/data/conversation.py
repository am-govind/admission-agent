"""Conversation store — backend is the source of truth for history."""
from __future__ import annotations

import uuid

from ..core import appdb


def new_conversation(username: str) -> str:
    cid = f"conv-{uuid.uuid4().hex[:12]}"
    appdb.execute(
        "INSERT INTO conversations (conversation_id, username) VALUES (?, ?)", [cid, username])
    return cid


def ensure_conversation(conversation_id: str | None, username: str) -> str:
    if not conversation_id:
        return new_conversation(username)
    appdb.execute(
        "INSERT OR IGNORE INTO conversations (conversation_id, username) VALUES (?, ?)",
        [conversation_id, username])
    return conversation_id


def next_turn(conversation_id: str) -> int:
    row = appdb.query_one(
        "SELECT COALESCE(MAX(turn_id), 0) FROM messages WHERE conversation_id = ?",
        [conversation_id])
    return int(row[0]) + 1 if row else 1


def add_message(conversation_id: str, turn_id: int, role: str, content: str) -> None:
    appdb.execute(
        "INSERT INTO messages (conversation_id, turn_id, role, content) VALUES (?, ?, ?, ?)",
        [conversation_id, turn_id, role, content])


def get_history(conversation_id: str, limit: int = 20) -> list[dict]:
    rows = appdb.query(
        "SELECT role, content FROM messages WHERE conversation_id = ? "
        "ORDER BY turn_id DESC, rowid DESC LIMIT ?", [conversation_id, limit])
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def message_count(conversation_id: str) -> int:
    row = appdb.query_one(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", [conversation_id])
    return int(row[0]) if row else 0
