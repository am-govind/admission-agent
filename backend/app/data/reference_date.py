"""Data-anchored reference date.

reference_date = MAX(joining_date) in rd26. The workbook's "Updated On" cell is
MAX(RD26_DUMP!H:H)+1, and its TODAY() therefore stands for the day after the last
recorded admission. Deriving every period from the data instead of the server clock
keeps answers identical to the delivered dump no matter when the refresh ran.
"""
from __future__ import annotations

import datetime as dt

from ..core.database import scalar, table_exists
from .schema import TABLE_RD26


def reference_date() -> dt.date:
    """Latest joining_date in rd26, falling back to today when nothing is loaded."""
    if not table_exists(TABLE_RD26):
        return dt.date.today()
    value = scalar(f"SELECT MAX(joining_date) FROM {TABLE_RD26}")
    if value is None:
        return dt.date.today()
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def updated_on(ref: dt.date | None = None) -> dt.date:
    """The sheet's 'Updated On' date: one day after the last admission (cell B1)."""
    return (ref or reference_date()) + dt.timedelta(days=1)


def month_bounds(ref: dt.date) -> tuple[dt.date, dt.date]:
    """First day of ref's month and first day of the next (mirrors the EOMONTH pair)."""
    first = ref.replace(day=1)
    nxt = first.replace(year=first.year + 1, month=1) if first.month == 12 \
        else first.replace(month=first.month + 1)
    return first, nxt


def next_month(first: dt.date) -> dt.date:
    """EDATE(first, 1) for a date that is already the first of a month."""
    return first.replace(year=first.year + 1, month=1) if first.month == 12 \
        else first.replace(month=first.month + 1)


def dod_latest(ref: dt.date) -> dt.date:
    """Most recent complete day for the DOD series.

    The sheet uses TODAY()-1, and its TODAY() is the day after the last admission, so
    the newest DOD column lands exactly on the reference date.
    """
    return ref


def dod_dates(ref: dt.date, days: int = 20) -> list[dt.date]:
    """The DOD calendar, newest first, matching columns M..AG."""
    latest = dod_latest(ref)
    return [latest - dt.timedelta(days=i) for i in range(days)]


def month_starts(ref: dt.date, months: int = 12) -> list[dt.date]:
    """Month start dates up to and including ref's month, oldest first (row 60)."""
    first, _ = month_bounds(ref)
    starts = [first]
    for _ in range(months - 1):
        prev = starts[0]
        starts.insert(0, prev.replace(year=prev.year - 1, month=12)
                      if prev.month == 1 else prev.replace(month=prev.month - 1))
    return starts
