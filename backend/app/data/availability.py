"""What data is actually loaded, and how fresh it is.

Every analytics function checks here before it computes. If a table is missing or is
missing a column the formula needs, the tool declines with a reason instead of
returning a number that looks authoritative but is not.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field

from ..core import appdb, database
from ..core.config import settings
from .schema import ANALYTICS_TABLES, REQUIRED_COLUMNS, TABLE_LABELS, TABLE_RD26

META_LAST_SUCCESS = "refresh_last_success"
META_LAST_ERROR = "refresh_last_error"
META_LAST_ATTEMPT = "refresh_last_attempt"
META_SOURCE = "refresh_source"
META_ROW_COUNTS = "refresh_row_counts"

# How long after the scheduled refresh time data is still considered current.
STALE_AFTER = dt.timedelta(days=1, hours=6)


@dataclass
class TableStatus:
    table: str
    label: str
    present: bool
    rows: int
    missing_columns: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.present and self.rows > 0 and not self.missing_columns

    @property
    def reason(self) -> str | None:
        if not self.present:
            return f"the {self.label} ({self.table}) has not been loaded yet"
        if self.rows == 0:
            return f"the {self.label} ({self.table}) is loaded but empty"
        if self.missing_columns:
            cols = ", ".join(self.missing_columns)
            return f"the {self.label} ({self.table}) is missing column(s): {cols}"
        return None


_cache: dict[str, TableStatus] = {}
_cache_generation = -1


def statuses(refresh: bool = False) -> dict[str, TableStatus]:
    """Status of every analytics table, cached until the data changes."""
    global _cache, _cache_generation
    generation = database._generation
    if refresh or generation != _cache_generation or not _cache:
        _cache = {t: _read_status(t) for t in ANALYTICS_TABLES}
        _cache_generation = generation
    return _cache


def _read_status(table: str) -> TableStatus:
    label = TABLE_LABELS.get(table, table)
    if not database.table_exists(table):
        return TableStatus(table=table, label=label, present=False, rows=0)
    columns = set(database.table_columns(table))
    missing = tuple(c for c in REQUIRED_COLUMNS.get(table, ()) if c not in columns)
    return TableStatus(table=table, label=label, present=True,
                       rows=database.row_count(table), missing_columns=missing)


def status(table: str) -> TableStatus:
    return statuses()[table]


def is_available(table: str) -> bool:
    return statuses()[table].usable


def unavailable_reason(*tables: str) -> str | None:
    """First blocking reason across the given tables, or None if all are usable."""
    current = statuses()
    for table in tables:
        entry = current.get(table)
        if entry is None:
            return f"unknown table {table}"
        if not entry.usable:
            return entry.reason
    return None


def missing_tables() -> list[str]:
    return [t for t, s in statuses().items() if not s.usable]


def row_counts() -> dict[str, int]:
    return {t: s.rows for t, s in statuses().items() if s.present}


# ---------- freshness ----------

def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def last_success() -> dt.datetime | None:
    return _parse(appdb.get_meta(META_LAST_SUCCESS))


def last_attempt() -> dt.datetime | None:
    return _parse(appdb.get_meta(META_LAST_ATTEMPT))


def last_error() -> str | None:
    return appdb.get_meta(META_LAST_ERROR)


def source_name() -> str | None:
    return appdb.get_meta(META_SOURCE)


def loaded_row_counts() -> dict[str, int]:
    raw = appdb.get_meta(META_ROW_COUNTS)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def refresh_due(now: dt.datetime | None = None) -> bool:
    """True when the most recent scheduled refresh has not yet succeeded.

    Driven by comparing the last success against the latest elapsed cutoff rather
    than by sleeping until a wall-clock time, so a restart or a missed window still
    triggers exactly one catch-up run.
    """
    zone = settings.refresh_zone
    now_local = (now or dt.datetime.now(zone)).astimezone(zone)
    target = settings.refresh_time
    cutoff = now_local.replace(hour=target.hour, minute=target.minute,
                               second=0, microsecond=0)
    if now_local < cutoff:
        # Today's window has not opened yet; the deadline that matters is yesterday's.
        cutoff -= dt.timedelta(days=1)
    success = last_success()
    return success is None or success.astimezone(zone) < cutoff


def is_stale(now: dt.datetime | None = None) -> bool:
    success = last_success()
    if success is None:
        return True
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - success) > STALE_AFTER


def staleness_note(now: dt.datetime | None = None) -> str | None:
    """Warning text prepended to answers when the data is behind schedule."""
    success = last_success()
    if success is None:
        if database.table_exists(TABLE_RD26):
            return None  # Loaded outside the audited path (e.g. tests); nothing to warn about.
        return "No data refresh has completed yet, so no figures are available."
    if not is_stale(now):
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    days = max(1, (now - success).days)
    note = (f"Heads-up: the data has not refreshed successfully in {days} day(s) "
            f"(last success {success.date().isoformat()}).")
    error = last_error()
    return f"{note} Last error: {error}" if error else note


def summary() -> dict:
    """Freshness and availability payload for GET /meta."""
    success = last_success()
    attempt = last_attempt()
    return {
        "source": source_name(),
        "lastSuccess": success.isoformat() if success else None,
        "lastAttempt": attempt.isoformat() if attempt else None,
        "lastError": last_error(),
        "stale": is_stale(),
        "rowCounts": row_counts(),
        "tables": {
            t: {"present": s.present, "rows": s.rows, "usable": s.usable,
                "missingColumns": list(s.missing_columns), "reason": s.reason}
            for t, s in statuses().items()
        },
    }
