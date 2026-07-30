"""Typed loading of raw sheet rows into DuckDB.

Every source funnels through here so there is exactly one place that decides how a
cell becomes a typed column. The load is three phases:

  1. canonicalise each cell to text and insert into `<table>__raw` (all VARCHAR);
  2. `CREATE TABLE <table>__staging AS SELECT <cast expressions> FROM <table>__raw`;
  3. atomically swap staging over the live table.

Splitting it this way means a malformed cell produces a NULL in one column instead of
aborting the whole load, and the live table is never partially written: the previous
day's data stays queryable until the new copy is complete.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
import os
import tempfile
from decimal import Decimal
from typing import Any, Iterable, Sequence

from ..core import database
from .schema import (BOOLEAN, DATE, DOUBLE, IDENTIFIER, INTEGER, REQUIRED_COLUMNS,
                     column_type, normalize_header)

log = logging.getLogger(__name__)

RowWindow = Sequence[Sequence[Any]]

# Excel/Sheets serial dates count days from this epoch.
_SERIAL_EPOCH = "DATE '1899-12-30'"

_TRUE_TEXT = ("true", "t", "yes", "y", "1")
_FALSE_TEXT = ("false", "f", "no", "n", "0")


class SchemaError(Exception):
    """The tab is present but does not carry the columns analytics needs."""


def canonical(value: Any) -> str | None:
    """Render one cell as text, without losing information.

    Dates become ISO so DuckDB can cast them directly, and whole floats lose their
    ".0" — `regno` arrives from openpyxl as 23540391.0 and must not end up as
    "23540391.0" or, worse, "2.3540391e+07".
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, Decimal):
        return str(value)
    text = str(value).strip()
    return text or None


def resolve_columns(table: str, header: Sequence[object]) -> list[str]:
    """Normalise header cells to column names, keeping sheet order.

    Blank headers are dropped and duplicates are suffixed, because DuckDB cannot
    hold two columns of the same name and a trailing blank column is common.
    """
    names: list[str] = []
    seen: dict[str, int] = {}
    for cell in header:
        name = normalize_header(cell)
        if not name:
            names.append("")
            continue
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        names.append(name)
    return names


def _check_required(table: str, columns: Sequence[str]) -> None:
    required = REQUIRED_COLUMNS.get(table, ())
    missing = [c for c in required if c not in columns]
    if missing:
        raise SchemaError(
            f"{table}: source tab is missing required column(s): {', '.join(missing)}")


def _cast_expr(table: str, column: str) -> str:
    """SQL that turns the raw VARCHAR column into its declared type."""
    col = f'"{column}"'
    kind = column_type(table, column)

    if kind in (IDENTIFIER, "VARCHAR"):
        return col
    if kind == BOOLEAN:
        true_list = ", ".join(f"'{v}'" for v in _TRUE_TEXT)
        false_list = ", ".join(f"'{v}'" for v in _FALSE_TEXT)
        return (f"CASE WHEN lower({col}) IN ({true_list}) THEN TRUE "
                f"WHEN lower({col}) IN ({false_list}) THEN FALSE END")
    if kind in (INTEGER, DOUBLE):
        # Retry stripped of currency/percent/thousands separators, which appear when a
        # sheet is read with formatting applied.
        cleaned = f"regexp_replace({col}, '[^0-9eE.+-]', '', 'g')"
        numeric = f"COALESCE(TRY_CAST({col} AS DOUBLE), TRY_CAST({cleaned} AS DOUBLE))"
        return f"CAST(ROUND({numeric}) AS BIGINT)" if kind == INTEGER else numeric
    if kind == DATE:
        return (
            "COALESCE("
            f"TRY_CAST({col} AS DATE), "
            f"CAST(TRY_STRPTIME({col}, '%d %b, %Y') AS DATE), "
            f"CAST(TRY_STRPTIME({col}, '%d-%b-%Y') AS DATE), "
            f"CAST(TRY_STRPTIME({col}, '%d/%m/%Y') AS DATE), "
            f"CASE WHEN TRY_CAST({col} AS DOUBLE) IS NOT NULL "
            f"THEN {_SERIAL_EPOCH} + CAST(ROUND(TRY_CAST({col} AS DOUBLE)) AS INTEGER) END"
            ")"
        )
    return col


def _write_csv(path: str, columns: Sequence[str], indices: Sequence[int], width: int,
               windows: Iterable[RowWindow]) -> int:
    """Stream the canonicalised rows to a CSV DuckDB can bulk-load."""
    total = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for window in windows:
            batch: list[list[str | None]] = []
            for row in window:
                # Sheets omits trailing empty cells, so short rows are normal.
                padded = list(row) + [None] * (width - len(row))
                if not any(v is not None and str(v).strip() != "" for v in padded):
                    continue
                batch.append([canonical(padded[i]) for i in indices])
            if batch:
                writer.writerows(batch)
                total += len(batch)
    return total


def load_table(table: str, header: Sequence[object], windows: Iterable[RowWindow]) -> int:
    """Load one table and swap it into place. Returns the row count loaded."""
    names = resolve_columns(table, header)
    kept = [(i, n) for i, n in enumerate(names) if n]
    if not kept:
        raise SchemaError(f"{table}: source tab has no usable header row")
    _check_required(table, [n for _, n in kept])

    raw = f"{table}__raw"
    staging = f"{table}__staging"
    columns = [n for _, n in kept]
    indices = [i for i, _ in kept]

    fd, csv_path = tempfile.mkstemp(prefix=f"{table}__", suffix=".csv")
    os.close(fd)
    try:
        total = _write_csv(csv_path, columns, indices, len(names), windows)

        database.write(f'DROP TABLE IF EXISTS "{raw}"')
        database.write(f'DROP TABLE IF EXISTS "{staging}"')
        database.write(
            f'CREATE TABLE "{raw}" (' + ", ".join(f'"{c}" VARCHAR' for c in columns) + ")")
        # Bulk load beats row-by-row inserts by more than two orders of magnitude at
        # this width: 42k rows is ~0.5s here versus ~130s via executemany.
        database.write(
            f'INSERT INTO "{raw}" SELECT * FROM read_csv({_sql_literal(csv_path)}, '
            "all_varchar=true, header=true, delim=',', quote='\"', escape='\"')")

        select = ", ".join(f'{_cast_expr(table, c)} AS "{c}"' for c in columns)
        database.write(f'CREATE TABLE "{staging}" AS SELECT {select} FROM "{raw}"')
        database.swap_staging(table, staging)
        database.write(f'DROP TABLE IF EXISTS "{raw}"')
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

    log.info("Loaded %s rows into %s", total, table)
    return total


def _sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"
