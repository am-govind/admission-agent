"""DuckDB connection management.

A single DuckDB file holds both the app tables (users, conversations, messages)
and the ingested data tables (rd26, rd25, finance_dump, targets).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

from .config import settings

_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return a process-wide DuckDB connection (thread-guarded)."""
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                Path(os.path.dirname(settings.duckdb_path) or ".").mkdir(parents=True, exist_ok=True)
                import time
                last_err = None
                for attempt in range(5):
                    try:
                        _conn = duckdb.connect(settings.duckdb_path)
                        _init_app_tables(_conn)
                        break
                    except duckdb.IOException as e:
                        last_err = e
                        if attempt == 4:
                            raise last_err
                        time.sleep(0.5)
    return _conn


def _init_app_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username   VARCHAR PRIMARY KEY,
            password_hash VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id VARCHAR PRIMARY KEY,
            username   VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS messages (
            conversation_id VARCHAR,
            turn_id    INTEGER,
            role       VARCHAR,
            content    VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS meta (
            key VARCHAR PRIMARY KEY,
            value VARCHAR
        );
        """
    )


def execute(sql: str, params: list | tuple | None = None):
    """Thread-safe execute returning fetched rows."""
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, params or [])
        return cur.fetchall()


def execute_dicts(sql: str, params: list | tuple | None = None) -> tuple[list[str], list[dict]]:
    """Returns (column_names, rows_as_dicts). No pandas needed."""
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, [dict(zip(cols, row)) for row in cur.fetchall()]


def execute_df(sql: str, params: list | tuple | None = None):
    conn = get_conn()
    with _lock:
        return conn.execute(sql, params or []).df()

