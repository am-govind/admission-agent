"""Conversation store — backend is the source of truth for history."""
from __future__ import annotations

import json
import uuid

from ..core import appdb

TITLE_MAX = 60


class NotOwned(Exception):
    """Raised when a conversation exists but belongs to a different user."""


def new_conversation(username: str) -> str:
    cid = f"conv-{uuid.uuid4().hex[:12]}"
    appdb.execute(
        "INSERT INTO conversations (conversation_id, username, updated_at) "
        "VALUES (?, ?, datetime('now'))", [cid, username])
    return cid


def ensure_conversation(conversation_id: str | None, username: str) -> str:
    """Return a conversation id owned by `username`, creating one if needed.

    Raises NotOwned when the caller passes an id belonging to somebody else: the ids are
    visible to the client once history is listed, so they cannot be trusted on the way in.
    """
    if not conversation_id:
        return new_conversation(username)
    row = appdb.query_one(
        "SELECT username FROM conversations WHERE conversation_id = ?", [conversation_id])
    if row is None:
        appdb.execute(
            "INSERT INTO conversations (conversation_id, username, updated_at) "
            "VALUES (?, ?, datetime('now'))", [conversation_id, username])
        return conversation_id
    if row[0] is not None and row[0] != username:
        raise NotOwned(conversation_id)
    return conversation_id


def owns(conversation_id: str, username: str) -> bool:
    row = appdb.query_one(
        "SELECT username FROM conversations WHERE conversation_id = ?", [conversation_id])
    return row is not None and (row[0] is None or row[0] == username)


def next_turn(conversation_id: str) -> int:
    row = appdb.query_one(
        "SELECT COALESCE(MAX(turn_id), 0) FROM messages WHERE conversation_id = ?",
        [conversation_id])
    return int(row[0]) + 1 if row else 1


def add_message(conversation_id: str, turn_id: int, role: str, content: str,
                render_state: dict | None = None) -> None:
    appdb.execute(
        "INSERT INTO messages (conversation_id, turn_id, role, content, render_state) "
        "VALUES (?, ?, ?, ?, ?)",
        [conversation_id, turn_id, role, content,
         json.dumps(render_state, ensure_ascii=False) if render_state else None])
    appdb.execute(
        "UPDATE conversations SET updated_at = datetime('now') WHERE conversation_id = ?",
        [conversation_id])


def get_history(conversation_id: str, limit: int = 20) -> list[dict]:
    rows = appdb.query(
        "SELECT role, content FROM messages WHERE conversation_id = ? "
        "ORDER BY turn_id DESC, rowid DESC LIMIT ?", [conversation_id, limit])
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def message_count(conversation_id: str) -> int:
    row = appdb.query_one(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", [conversation_id])
    return int(row[0]) if row else 0


# ---------- History browsing ----------
def derive_title(message: str) -> str:
    title = " ".join(message.split())
    return title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 1].rstrip() + "…"


def set_title(conversation_id: str, title: str) -> None:
    appdb.execute("UPDATE conversations SET title = ? WHERE conversation_id = ?",
                  [title, conversation_id])


def set_title_if_missing(conversation_id: str, message: str) -> None:
    """Name a conversation after its opening question, leaving a manual rename alone."""
    row = appdb.query_one(
        "SELECT title FROM conversations WHERE conversation_id = ?", [conversation_id])
    if row is not None and not row[0]:
        set_title(conversation_id, derive_title(message))


def list_for_user(username: str, limit: int = 200) -> list[dict]:
    """History for the sidebar.

    Conversations with no messages are hidden: a row is created as soon as a turn is
    attempted, so a guardrail-blocked opening question would otherwise leave an empty
    "New chat" entry sitting in the list forever.
    """
    rows = appdb.query(
        "SELECT c.conversation_id, c.title, c.created_at, "
        "       COALESCE(c.updated_at, c.created_at) AS updated_at, "
        "       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.conversation_id) "
        "           AS message_count "
        "FROM conversations c WHERE c.username = ? AND message_count > 0 "
        "ORDER BY updated_at DESC, c.created_at DESC LIMIT ?", [username, limit])
    return [{"conversationId": r[0], "title": r[1] or "New chat", "createdAt": r[2],
             "updatedAt": r[3], "messageCount": int(r[4])} for r in rows]


def get_transcript(conversation_id: str) -> list[dict]:
    rows = appdb.query(
        "SELECT role, content, render_state, created_at FROM messages "
        "WHERE conversation_id = ? ORDER BY turn_id ASC, rowid ASC", [conversation_id])
    return [{"role": r[0], "content": r[1], "renderState": _load_state(r[2]),
             "createdAt": r[3]} for r in rows]


def get_meta(conversation_id: str) -> dict | None:
    row = appdb.query_one(
        "SELECT conversation_id, title, created_at, COALESCE(updated_at, created_at) "
        "FROM conversations WHERE conversation_id = ?", [conversation_id])
    if row is None:
        return None
    return {"conversationId": row[0], "title": row[1] or "New chat",
            "createdAt": row[2], "updatedAt": row[3]}


def delete(conversation_id: str) -> None:
    appdb.execute("DELETE FROM messages WHERE conversation_id = ?", [conversation_id])
    appdb.execute("DELETE FROM conversation_memory WHERE conversation_id = ?",
                  [conversation_id])
    appdb.execute("DELETE FROM conversations WHERE conversation_id = ?", [conversation_id])


def _load_state(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
