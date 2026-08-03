"""Guarded open-ended querying.

The sealed metric functions cover the workbook. This is the escape hatch for
questions nobody anticipated, and it is the only place model-authored SQL runs. Four
independent guards apply, so no single mistake is load-bearing:

  1. DuckDB's own parser must report exactly one statement, of type SELECT;
  2. the query runs on a connection where the database is ATTACHed READ_ONLY, so DDL
     and DML are refused by the engine;
  3. that connection has enable_external_access=false, which blocks COPY ... TO,
     read_csv and read_parquet — READ_ONLY alone does not stop a query writing files;
  4. references to PII columns are rejected before execution.
"""
from __future__ import annotations

import logging
import re

import duckdb

from ..core.config import settings
from ..core.database import readonly_conn
from ..data import availability
from ..data.schema import ANALYTICS_TABLES, PII_COLUMNS, TABLE_COLUMN_TYPES
from .query import provenance
from .result import CHART_KINDS, ChartSpec, ToolResult

log = logging.getLogger(__name__)

_METRIC = "explore_data"

# Kept as an explicit check so the refusal message names the problem, even though
# guard 3 would also stop these.
_FORBIDDEN_FUNCTIONS = ("read_csv", "read_csv_auto", "read_parquet", "read_json",
                        "read_json_auto", "read_text", "read_blob", "glob",
                        "parquet_scan", "csv_scan", "install", "load_extension")


class ExplorerError(Exception):
    """The query was refused before it ran."""


def _pii_pattern() -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(sorted(PII_COLUMNS)) + r")\b", re.IGNORECASE)


_LEADING_COMMENT = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/|\s)+", re.DOTALL)


def _strip_leading_comments(text: str) -> str:
    return _LEADING_COMMENT.sub("", text, count=1).lstrip()


def validate(sql: str) -> None:
    """Raise ExplorerError unless the query is a single, safe SELECT."""
    text = (sql or "").strip()
    if not text:
        raise ExplorerError("No query was provided.")

    try:
        statements = duckdb.extract_statements(text)
    except duckdb.Error as e:
        raise ExplorerError(f"That is not valid DuckDB SQL: {e}") from e

    if len(statements) != 1:
        raise ExplorerError(
            f"Only one statement is allowed; {len(statements)} were provided.")
    kind = statements[0].type
    if kind != duckdb.StatementType.SELECT:
        raise ExplorerError(
            f"Only SELECT queries are allowed here, not {str(kind).split('.')[-1]}. "
            "Data is read-only.")

    # DuckDB classifies PRAGMA and similar introspection as SELECT, so require the
    # query to actually start as one.
    head = _strip_leading_comments(text)
    if not re.match(r"(?is)^(select|with)\b", head):
        first = (head.split(None, 1) or ["it"])[0]
        raise ExplorerError(
            f"A query must begin with SELECT or WITH, not {first.upper()}.")

    lowered = text.lower()
    for name in _FORBIDDEN_FUNCTIONS:
        if re.search(rf"\b{re.escape(name)}\s*\(", lowered):
            raise ExplorerError(f"The function {name}() is not available.")

    match = _pii_pattern().search(text)
    if match:
        raise ExplorerError(
            f"The column {match.group(1)!r} contains student personal data and cannot be "
            "selected or filtered on. Aggregate instead, or group by center, class or date.")


def explore(sql: str, limit: int | None = None,
            chart_kind: str | None = None,
            chart_title: str | None = None) -> ToolResult:
    """Run a validated read-only SELECT and return the rows."""
    try:
        validate(sql)
    except ExplorerError as e:
        # A refusal here is the guardrail doing its job, and is the single most useful
        # line in the log when reviewing what model-written SQL tried to do.
        log.warning("Explorer refused a query (%s): %.300s", e, sql)
        return ToolResult.unavailable(_METRIC, str(e))

    cap = max(1, min(int(limit or settings.explorer_max_rows), settings.explorer_max_rows))
    # Wrapping is simpler and safer than trying to detect or rewrite an existing LIMIT.
    guarded = f"SELECT * FROM ({sql.strip().rstrip(';')}) AS _guarded LIMIT {cap}"

    log.info("Explorer query (cap %s): %.300s", cap, " ".join(sql.split()))
    try:
        with readonly_conn() as conn:
            cursor = conn.execute(guarded)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
    except duckdb.Error as e:
        log.warning("Explorer query failed: %s", e)
        return ToolResult.unavailable(_METRIC, f"the query could not run: {e}")

    pattern = _pii_pattern()
    leaked = [c for c in columns if pattern.search(c)]
    if leaked:
        log.warning("Explorer result withheld; personal data in columns %s", leaked)
        return ToolResult.unavailable(
            _METRIC, f"the result exposes personal data column(s): {', '.join(leaked)}")

    table = [list(r) for r in rows]
    truncated = len(table) == cap
    summary = f"{len(table)} row(s) returned."
    if truncated:
        summary += f" Output is capped at {cap} rows, so there may be more."

    # Build a chart spec when the caller requests one and the data is chartable.
    # Convention: first column = x-axis label; every subsequent numeric column = a series.
    chart: ChartSpec | None = None
    kind = (chart_kind or "").lower()
    if kind in CHART_KINDS and len(columns) >= 2 and len(table) >= 2:
        x_col = columns[0]
        # Detect numeric columns by inspecting the first non-null value in each column.
        y_cols = []
        for ci, col in enumerate(columns[1:], 1):
            first_val = next((r[ci] for r in table if r[ci] is not None), None)
            if isinstance(first_val, (int, float)):
                y_cols.append(col)
        if y_cols:
            title = chart_title or summary
            chart = ChartSpec(kind=kind, x=x_col, y=y_cols, title=title)  # type: ignore[arg-type]

    return ToolResult(
        metric=_METRIC,
        summary=summary,
        values={"row_count": len(table), "truncated": truncated},
        columns=columns,
        rows=table,
        chart=chart,
        provenance=provenance(_METRIC, ["custom query"], [], None, row_count=len(table),
                              notes=[f"read-only query capped at {cap} rows"]),
    )


def describe_tables() -> ToolResult:
    """Tables, columns, types and row counts — what the model needs to write SQL."""
    statuses = availability.statuses()
    rows: list[list[object]] = []
    for table in ANALYTICS_TABLES:
        status = statuses[table]
        if not status.present:
            rows.append([table, status.label, 0, "not loaded"])
            continue
        from ..core.database import table_columns
        visible = [c for c in table_columns(table) if c not in PII_COLUMNS]
        rows.append([table, status.label, status.rows, ", ".join(visible)])

    return ToolResult(
        metric="describe_tables",
        summary=("Available tables and columns. Personal data columns "
                 f"({', '.join(sorted(PII_COLUMNS))}) are hidden and cannot be queried."),
        values={"tables": len([r for r in rows if r[2]])},
        columns=["Table", "Description", "Rows", "Columns"],
        rows=rows,
        provenance=provenance("describe_tables", list(ANALYTICS_TABLES), [], None),
    )


def list_locations() -> ToolResult:
    """Every center and region present in the data, so scope names can be checked."""
    from ..data import registry
    centers = registry.all_centers()
    if not centers:
        return ToolResult.unavailable("list_locations", "no admissions data is loaded")
    rows = [[c, registry.region_of(c) or ""] for c in centers]
    return ToolResult(
        metric="list_locations",
        summary=(f"{len(centers)} centers across {len(registry.all_regions())} regions: "
                 f"{', '.join(registry.all_regions())}."),
        values={"centers": len(centers), "regions": registry.all_regions()},
        columns=["Center", "Region"],
        rows=rows,
        provenance=provenance("list_locations", list(ANALYTICS_TABLES[:1]), [], None,
                              row_count=len(rows)),
    )


def data_freshness() -> ToolResult:
    """When the data last refreshed, what loaded, and what is missing."""
    info = availability.summary()
    rows: list[list[object]] = [
        ["Source", info.get("source") or "unknown"],
        ["Last successful refresh", info.get("lastSuccess") or "never"],
        ["Reference date (latest admission)", _reference_date_text()],
        ["Stale", "yes" if info.get("stale") else "no"],
    ]
    for table, meta in info.get("tables", {}).items():
        state = f"{meta['rows']:,} rows" if meta["usable"] else (meta["reason"] or "unusable")
        rows.append([table, state])
    if info.get("lastError"):
        rows.append(["Last error", info["lastError"]])

    return ToolResult(
        metric="data_freshness",
        summary=(f"Data source {info.get('source') or 'unknown'}; last successful refresh "
                 f"{info.get('lastSuccess') or 'never'}."),
        values={"stale": info.get("stale"), "lastSuccess": info.get("lastSuccess"),
                "missing": availability.missing_tables()},
        columns=["Item", "Value"],
        rows=rows,
        provenance=provenance("data_freshness", list(ANALYTICS_TABLES), [], None),
    )


def _reference_date_text() -> str:
    from ..data.reference_date import reference_date
    try:
        return reference_date().isoformat()
    except Exception:  # noqa: BLE001 - freshness must report even with no data loaded
        return "unknown"


def preview_columns(table: str) -> ToolResult:
    """Column names, declared types and distinct-value samples for one table."""
    metric = "preview_columns"
    name = (table or "").strip().lower()
    if name not in ANALYTICS_TABLES:
        return ToolResult.unavailable(
            metric, f"{table!r} is not a known table. Known tables: "
                    f"{', '.join(ANALYTICS_TABLES)}")
    reason = availability.unavailable_reason(name)
    if reason:
        return ToolResult.unavailable(metric, reason)

    from ..core.database import execute, table_columns
    declared = TABLE_COLUMN_TYPES.get(name, {})
    rows: list[list[object]] = []
    for column in table_columns(name):
        if column in PII_COLUMNS:
            continue
        distinct = execute(
            f'SELECT COUNT(DISTINCT "{column}") FROM {name}')[0][0]
        samples: list[object] = []
        if int(distinct or 0) <= 25:
            samples = [r[0] for r in execute(
                f'SELECT DISTINCT "{column}" FROM {name} '
                f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT 12')]
        rows.append([column, declared.get(column, "VARCHAR"), int(distinct or 0),
                     ", ".join(str(s) for s in samples)])

    return ToolResult(
        metric=metric,
        summary=f"{len(rows)} queryable columns in {name}.",
        values={"table": name, "columns": len(rows)},
        columns=["Column", "Type", "Distinct", "Sample values"],
        rows=rows,
        provenance=provenance(metric, [name], [], None, row_count=len(rows)),
    )
