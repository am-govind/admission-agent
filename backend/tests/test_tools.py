"""Tool-layer contracts.

The important test here is the thin-wrapper check: business thresholds must be declared
once, in analytics/filters.py, because the workbook deliberately uses `> 3498` for some
metrics and `>= 3498` for others. A copy of that literal inside a tool wrapper is a
second source of truth that will drift.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.agent.tools import REGISTRY, get_tool, schemas_for
from app.analytics.result import ToolResult

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "agent" / "tools"
FILTERS = Path(__file__).resolve().parents[1] / "app" / "analytics" / "filters.py"
WRAPPERS = sorted(TOOLS_DIR.glob("*_tools.py"))


def _threshold_literals() -> set[str]:
    """Numeric literals used as business thresholds in the sealed filter definitions."""
    found = set()
    for line in FILTERS.read_text().splitlines():
        code = line.split("#", 1)[0]
        for match in re.finditer(r"[<>]=?\s*'?(\d{3,})", code):
            found.add(match.group(1))
    return found


def test_filters_actually_define_thresholds():
    """Guards the guard: if this is empty the wrapper test below proves nothing."""
    assert _threshold_literals(), "no thresholds parsed out of analytics/filters.py"


def test_no_threshold_literals_in_tool_wrappers():
    thresholds = _threshold_literals()
    offences = []
    for path in TOOLS_DIR.glob("*.py"):
        text = path.read_text()
        for literal in thresholds:
            if literal in text:
                offences.append(f"{path.name} contains threshold {literal}")
    assert not offences, (
        "business thresholds must live only in analytics/filters.py: " + "; ".join(offences))


def test_wrapper_modules_exist():
    assert WRAPPERS, "no *_tools.py wrapper modules found"


def test_wrappers_never_touch_the_database():
    """A wrapper that queries directly bypasses the sealed filters and the provenance."""
    # A SELECT ... FROM pair rather than the bare word, which appears legitimately in
    # explore_data's description.
    sql = re.compile(r"\bSELECT\b[\s\S]{0,300}?\bFROM\b", re.IGNORECASE)
    for path in WRAPPERS:
        text = path.read_text()
        assert not sql.search(text), f"{path.name} writes SQL"
        for forbidden in ("core.database", "core import database", "duckdb"):
            assert forbidden not in text, f"{path.name} reaches for {forbidden}"


def test_registry_size_and_uniqueness():
    assert len(REGISTRY) == 28
    assert len(set(REGISTRY)) == len(REGISTRY)


def test_schemas_are_openai_shaped():
    schemas = schemas_for(tuple(REGISTRY))
    assert len(schemas) == len(REGISTRY)
    for schema in schemas:
        assert schema["type"] == "function"
        function = schema["function"]
        assert function["name"] in REGISTRY
        assert function["description"]
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert "properties" in parameters
        # A $ref would send the model looking for a definition that is not in the payload.
        assert "$ref" not in str(parameters)


def test_every_tool_returns_a_tool_result():
    for name in ("get_fresh_registrations", "get_admissions_summary", "get_arpu",
                 "get_cancellations", "describe_tables"):
        result = get_tool(name).run({})
        assert isinstance(result, ToolResult)
        assert result.metric


def test_unknown_parameter_is_refused_not_ignored():
    """`centre` silently dropped would answer a center question with global numbers."""
    result = get_tool("get_fresh_registrations").run({"centre": "Pune"})
    assert not result.ok
    assert "not valid" in (result.unavailable_reason or "")


def test_wrong_type_is_refused():
    result = get_tool("get_monthly_trend").run({"months": "many"})
    assert not result.ok
    assert "not valid" in (result.unavailable_reason or "")


def test_out_of_range_parameter_is_refused():
    result = get_tool("get_monthly_trend").run({"months": 500})
    assert not result.ok


def test_run_wraps_analytics_failure_as_not_ok():
    """A crash inside analytics must become a decline, not a 500 mid-conversation."""
    result = get_tool("explore_data").run({"sql": "SELECT * FROM no_such_table"})
    assert not result.ok
    assert result.unavailable_reason or result.error
