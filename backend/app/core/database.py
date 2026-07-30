"""DuckDB connection management for the analytics tables.

This file holds ONLY ingested analytics data (rd26, rd25, finance_dump, targets)
and is rebuilt wholesale by each refresh. Application state lives in core.appdb.

Two connections are maintained:
  - a read-write connection used by ingestion and the sealed analytics functions;
  - a read-only snapshot, attached from a separate in-memory connection, which the
    explorer tool uses so that DDL/DML is refused by the engine rather than by a
    regex over the SQL text.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import duckdb

from .config import settings

log = logging.getLogger(__name__)

# Schema name the read-only snapshot is attached under.
RO_SCHEMA = "snap"

_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None

_ro_lock = threading.Lock()
_ro_conn: duckdb.DuckDBPyConnection | None = None
_ro_generation = -1

# Bumped after every write. The read-only snapshot is frozen at attach time, so it
# must be re-attached whenever this changes or the explorer would serve stale data.
_generation = 0


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return the process-wide read-write connection (thread-guarded)."""
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                settings.duckdb_file.parent.mkdir(parents=True, exist_ok=True)
                last_err: Exception | None = None
                for attempt in range(5):
                    try:
                        _conn = duckdb.connect(str(settings.duckdb_file))
                        break
                    except duckdb.IOException as e:
                        last_err = e
                        if attempt == 4:
                            raise
                        time.sleep(0.5)
                if _conn is None and last_err is not None:
                    raise last_err
    return _conn


def reset() -> None:
    """Close cached connections so a new duckdb_path takes effect (used by tests)."""
    global _conn, _ro_conn, _ro_generation, _generation
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
    with _ro_lock:
        if _ro_conn is not None:
            _ro_conn.close()
            _ro_conn = None
        _ro_generation = -1
    _generation = 0


def bump_generation() -> None:
    """Mark the analytics data as changed, invalidating the read-only snapshot."""
    global _generation
    _generation += 1


# ---------- read-write helpers ----------

def execute(sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
    conn = get_conn()
    with _lock:
        return conn.execute(sql, list(params or [])).fetchall()


def execute_dicts(sql: str, params: Sequence[Any] | None = None) -> tuple[list[str], list[dict]]:
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, list(params or []))
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, [dict(zip(cols, row)) for row in cur.fetchall()]


def write(sql: str, params: Sequence[Any] | None = None) -> None:
    """Run a statement that changes data, then invalidate the read-only snapshot."""
    conn = get_conn()
    with _lock:
        conn.execute(sql, list(params or []))
    bump_generation()


def scalar(sql: str, params: Sequence[Any] | None = None, default: Any = None) -> Any:
    rows = execute(sql, params)
    if not rows or rows[0][0] is None:
        return default
    return rows[0][0]


def table_exists(table: str) -> bool:
    return bool(
        execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = ?",
            [table],
        )
    )


def table_columns(table: str) -> list[str]:
    return [
        r[0]
        for r in execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
            [table],
        )
    ]


def row_count(table: str) -> int:
    if not table_exists(table):
        return 0
    return int(scalar(f'SELECT COUNT(*) FROM "{table}"', default=0))


def swap_staging(table: str, staging: str) -> None:
    """Replace `table` with `staging` atomically.

    The expensive load happens into the staging table beforehand, so the write lock
    is held only for two renames. A failure before this point leaves the previous
    good data in place.
    """
    conn = get_conn()
    with _lock:
        old = f"{table}__old"
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(f'DROP TABLE IF EXISTS "{old}"')
            if _table_exists_unlocked(conn, table):
                conn.execute(f'ALTER TABLE "{table}" RENAME TO "{old}"')
            conn.execute(f'ALTER TABLE "{staging}" RENAME TO "{table}"')
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute(f'DROP TABLE IF EXISTS "{old}"')
    bump_generation()


def _table_exists_unlocked(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = ?",
            [table],
        ).fetchall()
    )


# ---------- read-only snapshot ----------

def _open_readonly() -> duckdb.DuckDBPyConnection:
    """Build a fresh in-memory connection with the analytics file attached read-only.

    `enable_external_access=false` is what actually stops COPY ... TO, read_csv and
    read_parquet from touching the filesystem — READ_ONLY alone does not. It has to
    be set after ATTACH, because attaching is itself external access, and DuckDB
    then refuses to re-enable it on this connection. That also means the snapshot
    cannot be refreshed with DETACH/ATTACH, so a stale snapshot is replaced by
    building a whole new connection.
    """
    conn = duckdb.connect(":memory:")
    conn.execute(f"ATTACH '{settings.duckdb_file}' AS {RO_SCHEMA} (READ_ONLY)")
    # So user SQL can say `FROM rd26` without qualifying the schema.
    conn.execute(f"USE {RO_SCHEMA}")
    conn.execute("SET enable_external_access=false")
    return conn


@contextmanager
def readonly_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Yield a connection on which writes are refused by DuckDB itself.

    Serialised: a single DuckDB connection is not meant for concurrent use, and
    explorer queries are capped and infrequent.
    """
    global _ro_conn, _ro_generation
    # Ensure the file exists before attaching to it.
    get_conn()
    with _ro_lock:
        if _ro_conn is None or _ro_generation != _generation:
            if _ro_conn is not None:
                _ro_conn.close()
            _ro_conn = _open_readonly()
            _ro_generation = _generation
        yield _ro_conn
