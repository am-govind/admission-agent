"""One-time copy of application state out of the pre-split DuckDB file.

Before the storage split, users/conversations/messages lived in the same DuckDB
file as the analytics tables. This moves them into SQLite once, so existing logins
and chat history survive the upgrade. It is a no-op on a fresh install.
"""
from __future__ import annotations

import logging

import duckdb

from . import appdb
from .config import settings

log = logging.getLogger(__name__)

_FLAG = "app_state_migrated"


def migrate_app_state() -> dict[str, int]:
    """Copy legacy app tables into SQLite. Safe to call on every startup."""
    if appdb.get_meta(_FLAG):
        return {}

    legacy = settings.legacy_duckdb_file
    if not legacy.exists() or legacy == settings.duckdb_file:
        appdb.set_meta(_FLAG, "1")
        return {}

    moved: dict[str, int] = {}
    try:
        conn = duckdb.connect(str(legacy), read_only=True)
    except Exception as e:  # noqa: BLE001 - a locked or corrupt legacy file must not block startup
        log.warning("Skipping app-state migration, cannot open %s: %s", legacy, e)
        return {}

    try:
        moved["users"] = _copy(
            conn,
            "SELECT username, password_hash FROM users",
            "INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)",
        )
        moved["conversations"] = _copy(
            conn,
            "SELECT conversation_id, username FROM conversations",
            "INSERT OR IGNORE INTO conversations (conversation_id, username) VALUES (?, ?)",
        )
        moved["messages"] = _copy(
            conn,
            "SELECT conversation_id, turn_id, role, content FROM messages",
            "INSERT INTO messages (conversation_id, turn_id, role, content) VALUES (?, ?, ?, ?)",
        )
    finally:
        conn.close()

    appdb.set_meta(_FLAG, "1")
    if any(moved.values()):
        log.info("Migrated legacy app state from %s: %s", legacy, moved)
    return {k: v for k, v in moved.items() if v}


def _copy(conn: duckdb.DuckDBPyConnection, select_sql: str, insert_sql: str) -> int:
    try:
        rows = conn.execute(select_sql).fetchall()
    except duckdb.Error:
        return 0  # Table absent in the legacy file.
    if not rows:
        return 0
    appdb.executemany(insert_sql, [[_text(v) for v in row] for row in rows])
    return len(rows)


def _text(value: object) -> object:
    return value if value is None or isinstance(value, (str, int, float)) else str(value)
