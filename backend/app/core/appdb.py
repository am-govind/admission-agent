"""SQLite store for durable application state.

Deliberately separate from the analytics DuckDB file: that file is dropped and
rebuilt by every daily refresh, so anything which must outlive a refresh — users,
chat history, conversation memory, refresh audit — lives here instead.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Sequence

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    username        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    conversation_id TEXT NOT NULL,
    turn_id         INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id, turn_id);

CREATE TABLE IF NOT EXISTS conversation_memory (
    conversation_id TEXT NOT NULL,
    key             TEXT NOT NULL,
    value           TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (conversation_id, key)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS refresh_runs (
    run_id      TEXT PRIMARY KEY,
    trigger     TEXT NOT NULL,
    source      TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    row_counts  TEXT,
    error       TEXT
);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialised = False


def _connect() -> sqlite3.Connection:
    path = settings.appdb_file
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    # WAL lets the refresh thread write audit rows while requests read.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_conn() -> sqlite3.Connection:
    """One connection per thread; sqlite3 objects are not safe to share."""
    global _initialised
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    if not _initialised:
        with _init_lock:
            if not _initialised:
                conn.executescript(_SCHEMA)
                conn.commit()
                _initialised = True
    return conn


def reset() -> None:
    """Drop cached connections so a new appdb_path takes effect (used by tests)."""
    global _initialised
    with _init_lock:
        _initialised = False
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def execute(sql: str, params: Sequence[Any] | None = None) -> None:
    conn = get_conn()
    with conn:
        conn.execute(sql, tuple(params or ()))


def executemany(sql: str, rows: Sequence[Sequence[Any]]) -> None:
    conn = get_conn()
    with conn:
        conn.executemany(sql, [tuple(r) for r in rows])


def query(sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
    return get_conn().execute(sql, tuple(params or ())).fetchall()


def query_one(sql: str, params: Sequence[Any] | None = None) -> tuple | None:
    return get_conn().execute(sql, tuple(params or ())).fetchone()


def get_meta(key: str) -> str | None:
    row = query_one("SELECT value FROM meta WHERE key = ?", [key])
    return row[0] if row else None


def set_meta(key: str, value: str) -> None:
    execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [key, value],
    )


def all_meta() -> dict[str, str]:
    return {k: v for k, v in query("SELECT key, value FROM meta")}
