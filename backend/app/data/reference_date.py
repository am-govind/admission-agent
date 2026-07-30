"""Data-anchored reference date.

reference_date = MAX(joining_date) in rd26 (mirrors sheet cell B1 = MAX(H:H)).
All "this month" / "yesterday" / DOD logic derives from this, NOT the server clock,
so numbers always match the delivered dump regardless of pull timing.
"""
from __future__ import annotations

import datetime as dt

from ..core.database import execute
from .schema import TABLE_RD26


def reference_date() -> dt.date:
    sql = f"""
        SELECT MAX(
            COALESCE(
                TRY_CAST(joining_date AS DATE),
                TRY_STRPTIME(joining_date, '%d %b, %Y'),
                TRY_STRPTIME(joining_date, '%d-%b-%Y'),
                TRY_STRPTIME(joining_date, '%Y-%m-%d')
            )
        ) FROM {TABLE_RD26}
    """
    rows = execute(sql)
    if rows and rows[0][0] is not None:
        val = rows[0][0]
        return val if isinstance(val, dt.date) else dt.date.fromisoformat(str(val))
    return dt.date.today()


def month_bounds(ref: dt.date) -> tuple[dt.date, dt.date]:
    """First day of ref's month and first day of next month (matches EOMONTH logic)."""
    first = ref.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    return first, nxt


def yesterday(ref: dt.date) -> dt.date:
    """DOD 'latest' date = reference_date - 1 (mirrors today()-1 on the data)."""
    return ref - dt.timedelta(days=1)
