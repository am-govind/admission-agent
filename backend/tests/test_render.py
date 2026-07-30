"""Rendering and scheduling.

Rendering: tool results become native table/chart blocks, so what the frontend draws is
the tool's own data rather than something the model retyped.
Scheduling: the refresh is catch-up driven, so a restart must not skip or repeat a day.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.agent import runtime
from app.analytics import admissions, revenue, rollups
from app.core import appdb
from app.core.config import settings
from app.data import availability


def test_a_table_result_yields_a_chart_and_a_table():
    blocks, provenance = runtime._blocks([rollups.region_rollup("registrations")])
    assert [b.type for b in blocks] == ["chart", "table"]
    assert provenance and "region_rollup" in provenance[0]


def test_chart_data_is_keyed_by_column_name():
    """Recharts reads objects by dataKey; a list of cells would render an empty chart."""
    chart = next(b for b in runtime._blocks([rollups.region_rollup("registrations")])[0]
                 if b.type == "chart")
    x, y = chart.data["x"], chart.data["y"]
    assert all(isinstance(row, dict) and x in row for row in chart.data["rows"])
    assert all(key in chart.data["rows"][0] for key in y)


def test_totals_are_excluded_from_the_chart_but_kept_in_the_table():
    result = rollups.region_rollup("registrations")
    blocks, _ = runtime._blocks([result])
    chart = next(b for b in blocks if b.type == "chart")
    table = next(b for b in blocks if b.type == "table")
    labels = [str(row[chart.data["x"]]).lower() for row in chart.data["rows"]]
    assert "grand total" not in labels, "a total row would dwarf every real bar"
    assert len(table.data["rows"]) > len(chart.data["rows"])


def test_table_rows_are_lists_of_cells():
    table = next(b for b in runtime._blocks([admissions.classwise_breakdown()])[0]
                 if b.type == "table")
    assert isinstance(table.data["rows"][0], list)
    assert len(table.data["rows"][0]) == len(table.data["columns"])


def test_repeated_results_render_once():
    result = rollups.region_rollup("registrations")
    blocks, provenance = runtime._blocks([result, result, result])
    assert [b.type for b in blocks] == ["chart", "table"]
    assert len(provenance) == 1


def test_scalar_results_produce_no_blocks():
    blocks, provenance = runtime._blocks([revenue.arpu()])
    assert blocks == []
    assert provenance, "a scalar answer still has to say where it came from"


def test_declines_produce_no_blocks():
    blocks, _ = runtime._blocks([admissions.fresh_registrations(center="Atlantis")])
    assert blocks == []


def test_block_ids_are_unique():
    blocks, _ = runtime._blocks([rollups.region_rollup("registrations"),
                                 admissions.classwise_breakdown()])
    ids = [b.id for b in blocks]
    assert len(set(ids)) == len(ids)


# ---------- scheduling ----------

@pytest.fixture(autouse=True)
def restore_last_success():
    """These tests rewrite the refresh clock, so put it back for everyone else."""
    original = appdb.get_meta(availability.META_LAST_SUCCESS)
    yield
    appdb.set_meta(availability.META_LAST_SUCCESS, original or "")


def _set_last_success(moment: dt.datetime | None) -> None:
    appdb.set_meta(availability.META_LAST_SUCCESS, moment.isoformat() if moment else "")


def test_refresh_is_due_when_nothing_has_ever_run():
    _set_last_success(None)
    assert availability.refresh_due()


def test_refresh_is_not_due_again_after_todays_run():
    zone = settings.refresh_zone
    now = dt.datetime.now(zone).replace(hour=9, minute=0, second=0, microsecond=0)
    _set_last_success(now.replace(minute=35))
    assert not availability.refresh_due(now)


def test_a_missed_window_is_caught_up():
    """Process was down at 08:30: it must refresh as soon as it is back, not wait a day."""
    zone = settings.refresh_zone
    now = dt.datetime.now(zone).replace(hour=14, minute=0, second=0, microsecond=0)
    _set_last_success(now - dt.timedelta(days=2))
    assert availability.refresh_due(now)


def test_before_the_window_yesterdays_run_still_counts():
    zone = settings.refresh_zone
    now = dt.datetime.now(zone).replace(hour=7, minute=0, second=0, microsecond=0)
    _set_last_success(now - dt.timedelta(hours=22))  # yesterday, after the cutoff
    assert not availability.refresh_due(now)


def test_staleness_note_appears_only_when_overdue():
    zone = settings.refresh_zone
    fresh = dt.datetime.now(zone)
    _set_last_success(fresh)
    assert availability.staleness_note() is None

    _set_last_success(fresh - dt.timedelta(days=4))
    note = availability.staleness_note()
    assert note and "day" in note
