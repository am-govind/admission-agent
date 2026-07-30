"""Roll-up, exploration and data-description tools. Wrappers only."""
from __future__ import annotations

from ...analytics import explorer, rollups
from ...analytics.result import ToolResult
from .registry import (ExploreParams, MetricParams, MetricRegionParams, NoParams,
                       TableParams, tool)


# ---------- roll-ups ----------

@tool("get_region_rollup",
      "One row per region plus a grand total, for a chosen metric. Use for "
      "'compare regions' or 'company-wide breakdown' questions.",
      MetricParams)
def get_region_rollup(metric: str = "registrations") -> ToolResult:
    return rollups.region_rollup(metric_name=metric)


@tool("get_center_rollup",
      "One row per center plus a subtotal, for a chosen metric, ranked highest first. "
      "Use for 'which center is best/worst' and league-table questions.",
      MetricRegionParams)
def get_center_rollup(metric: str = "registrations",
                      region: str | None = None) -> ToolResult:
    return rollups.center_rollup(metric_name=metric, region=region)


@tool("get_target_scoreboard",
      "Registration and monthly achievement against target for every region. Use for "
      "'are we on track' questions.",
      NoParams)
def get_target_scoreboard() -> ToolResult:
    return rollups.target_scoreboard()


# ---------- describing the data ----------

@tool("describe_tables",
      "List the available tables with their row counts and queryable columns. Call this "
      "before writing a custom query.",
      NoParams)
def describe_tables() -> ToolResult:
    return explorer.describe_tables()


@tool("preview_columns",
      "For one table, list each queryable column with its type, distinct-value count "
      "and sample values. Use to discover the exact spelling of category values.",
      TableParams)
def preview_columns(table: str) -> ToolResult:
    return explorer.preview_columns(table)


@tool("list_centers",
      "Every center and region present in the data. Use to check a name or to answer "
      "'which centers do we have'.",
      NoParams)
def list_centers() -> ToolResult:
    return explorer.list_locations()


@tool("get_data_freshness",
      "When the data last refreshed, which tables loaded, the reference date and any "
      "refresh error. Use when asked how current the numbers are.",
      NoParams)
def get_data_freshness() -> ToolResult:
    return explorer.data_freshness()


# ---------- the escape hatch ----------

@tool("explore_data",
      "Run a custom read-only SELECT against the admissions tables. Use ONLY when no "
      "dedicated metric tool fits the question, because dedicated tools carry the "
      "audited business rules and this does not. Call describe_tables first if unsure "
      "of the schema.",
      ExploreParams)
def explore_data(sql: str, limit: int | None = None) -> ToolResult:
    return explorer.explore(sql, limit=limit)
