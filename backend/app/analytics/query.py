"""Shared query plumbing for the analytics functions.

All SQL is parameterised, and every function checks data availability before it runs
so a missing tab produces an explicit decline rather than a DuckDB error.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Sequence

from ..core.database import execute, scalar
from ..data import availability
from ..data.reference_date import reference_date
from ..data.schema import TABLE_TARGETS
from .filters import Scope, describe_filters
from .result import Provenance, ToolResult


def require(metric: str, *tables: str) -> ToolResult | None:
    """Return a decline if any required table is unusable, else None."""
    reason = availability.unavailable_reason(*tables)
    return ToolResult.unavailable(metric, reason) if reason else None


def _where(clauses: Sequence[str]) -> str:
    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def count_rows(table: str, clauses: Sequence[str], params: Sequence[Any]) -> int:
    """COUNTIFS equivalent."""
    sql = f"SELECT COUNT(*) FROM {table}{_where(clauses)}"
    return int(scalar(sql, params, default=0) or 0)


def avg_column(table: str, column: str, clauses: Sequence[str],
               params: Sequence[Any]) -> float | None:
    """AVERAGEIFS equivalent. Returns None when nothing matches, as AVERAGEIFS errors."""
    sql = f"SELECT AVG({column}) FROM {table}{_where(clauses)}"
    value = scalar(sql, params)
    return float(value) if value is not None else None


def sum_column(table: str, column: str, clauses: Sequence[str],
               params: Sequence[Any]) -> float:
    sql = f"SELECT COALESCE(SUM({column}), 0) FROM {table}{_where(clauses)}"
    return float(scalar(sql, params, default=0) or 0)


def select_rows(table: str, select: str, clauses: Sequence[str], params: Sequence[Any],
                group_by: str | None = None, order_by: str | None = None,
                limit: int | None = None) -> list[tuple]:
    sql = f"SELECT {select} FROM {table}{_where(clauses)}"
    if group_by:
        sql += f" GROUP BY {group_by}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return execute(sql, params)


def pct(numerator: float | int | None, denominator: float | int | None) -> float | None:
    """IFERROR(a/b, ...) equivalent — a zero or missing denominator yields None."""
    if not denominator or numerator is None:
        return None
    return float(numerator) / float(denominator)


def provenance(metric: str, tables: Sequence[str], clauses: Sequence[str],
               scope: Scope | None = None, row_count: int | None = None,
               ref: dt.date | None = None, notes: Sequence[str] = ()) -> Provenance:
    return Provenance(
        metric=metric,
        source_tables=list(tables),
        filters=describe_filters([c for c in clauses if "?" not in c]),
        reference_date=(ref or reference_date()).isoformat(),
        scope=scope.describe() if scope else "all centers",
        row_count=row_count,
        notes=list(notes),
    )


def target_lookup(column: str, scope: Scope, aggregate: str = "SUM") -> float | None:
    """Look up a target for a scope, or None when targets are not loaded.

    Counts aggregate with SUM across a region; ARPU is a per-student rate and
    aggregates with AVG.
    """
    if not availability.is_available(TABLE_TARGETS):
        return None
    from ..core.database import table_columns
    if column not in table_columns(TABLE_TARGETS):
        return None
    sql = f"SELECT {aggregate}({column}) FROM {TABLE_TARGETS}{_where(scope.clauses)}"
    value = scalar(sql, scope.params)
    return float(value) if value is not None else None


def fmt_int(value: float | int | None) -> str:
    return "n/a" if value is None else f"{int(round(value)):,}"


def fmt_money(value: float | int | None) -> str:
    return "n/a" if value is None else f"₹{value:,.0f}"


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"
