"""Explorer guardrails.

The explorer is the one path where model-written SQL reaches the database, so it is the
one place where a prompt injection could try to mutate data, read the filesystem or
exfiltrate student names. Defence is layered: statement-shape checks here, plus a
read-only ATTACH with external access disabled in core/database.py.
"""
from __future__ import annotations

import pytest

from app.analytics import explorer
from app.core.config import settings

WRITES = [
    "DROP TABLE rd26",
    "DELETE FROM rd26",
    "UPDATE rd26 SET center = 'x'",
    "INSERT INTO rd26 (center) VALUES ('x')",
    "CREATE TABLE evil AS SELECT 1",
    "ALTER TABLE rd26 ADD COLUMN x INT",
    "ATTACH 'other.duckdb' AS other",
]

ESCAPES = [
    "COPY (SELECT 1) TO '/tmp/leak.csv'",
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_parquet('/etc/passwd')",
    "PRAGMA database_list",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SET enable_external_access=true",
]


@pytest.mark.parametrize("sql", WRITES)
def test_writes_are_refused(sql):
    result = explorer.explore(sql)
    assert not result.ok, f"write was allowed: {sql}"


@pytest.mark.parametrize("sql", ESCAPES)
def test_escapes_are_refused(sql):
    result = explorer.explore(sql)
    assert not result.ok, f"escape was allowed: {sql}"


def test_multiple_statements_are_refused():
    result = explorer.explore("SELECT 1; DROP TABLE rd26")
    assert not result.ok


def test_comment_prefix_does_not_smuggle_a_write():
    result = explorer.explore("-- harmless\n/* nothing here */ DELETE FROM rd26")
    assert not result.ok


def test_pii_columns_are_refused():
    for sql in ("SELECT student_name FROM rd26",
                "SELECT regno FROM rd26",
                "SELECT r.student_name AS n FROM rd26 r"):
        assert not explorer.explore(sql).ok, f"PII was exposed: {sql}"


def test_a_plain_select_works():
    result = explorer.explore("SELECT region, COUNT(*) AS students FROM rd26 GROUP BY region")
    assert result.ok, result.unavailable_reason or result.error
    assert result.columns == ["region", "students"]
    assert result.rows


def test_a_with_clause_works():
    result = explorer.explore(
        "WITH per_region AS (SELECT region, COUNT(*) AS n FROM rd26 GROUP BY region) "
        "SELECT * FROM per_region ORDER BY n DESC")
    assert result.ok, result.unavailable_reason or result.error


def test_row_cap_is_enforced():
    result = explorer.explore("SELECT center FROM rd26", limit=100_000)
    assert result.ok
    assert len(result.rows) <= settings.explorer_max_rows


def test_the_data_is_still_intact():
    """The whole point: none of the attempts above changed anything."""
    from app.core import database
    from app.data.schema import TABLE_RD26

    assert database.row_count(TABLE_RD26) > 0


def test_describe_tables_lists_the_loaded_tables():
    result = explorer.describe_tables()
    assert result.ok
    assert any("rd26" in str(row[0]) for row in result.rows)


def test_freshness_is_reported():
    assert explorer.data_freshness().ok
