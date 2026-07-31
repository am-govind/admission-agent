"""Comparisons render as one chart, whichever route produced them.

A comparison can arrive two ways — one call with `compare`, or one call per scope that
the render layer merges. Both must produce the same shape, because the frontend only
knows how to draw one thing. The failure to guard against is a merge that looks right but
mislabels or drops a series, which is invisible in a chart.
"""
from __future__ import annotations

from app.agent import runtime
from app.analytics import admissions, revenue, rollups, series


def _chart(results):
    blocks, _ = runtime._blocks(results)
    return next(b for b in blocks if b.type == "chart")


# ---------- one call with compare ----------

def test_compare_returns_one_result_naming_every_series():
    result = admissions.dod_admissions(compare=["Maharashtra", "South"], days=5)
    assert result.ok, result.decline_reason()
    assert len(result.chart.y) == 2
    assert result.columns == [result.chart.x, *result.chart.y]


def test_compare_puts_both_series_on_every_row():
    result = admissions.dod_admissions(compare=["Maharashtra", "South"], days=5)
    assert all(len(row) == 3 for row in result.rows)


def test_compared_values_match_the_standalone_calls():
    """Compared and standalone series must be the same query, not a similar one."""
    merged = admissions.monthly_trend(compare=["Pune", "Nagpur"], months=4)
    for index, term in enumerate(("Pune", "Nagpur"), start=1):
        alone = admissions.monthly_trend(center=term, months=4)
        assert [row[index] for row in merged.rows] == [row[1] for row in alone.rows]


def test_compare_works_for_cities_and_regions_alike():
    for terms in (["Pune", "Nagpur"], ["Maharashtra", "South"],
                  ["Pune", "Maharashtra"]):
        result = admissions.monthly_trend(compare=terms, months=3)
        assert result.ok, f"{terms}: {result.decline_reason()}"
        assert len(result.chart.y) == 2


def test_compare_titles_name_the_scopes():
    result = admissions.dod_admissions(compare=["Maharashtra", "South"], days=5)
    assert "vs" in result.chart.title
    for label in result.chart.y:
        assert label in result.chart.title


def test_a_bar_metric_keeps_its_kind_when_compared():
    result = admissions.classwise_breakdown(compare=["Pune", "Nagpur"])
    assert result.chart.kind == "bar"
    assert len(result.rows) == 9


def test_compare_declines_when_a_term_cannot_be_resolved():
    """Dropping the bad series would answer half the question and look complete."""
    result = admissions.dod_admissions(compare=["Maharashtra", "Atlantis"])
    assert not result.ok
    assert "Atlantis" in result.decline_reason()


def test_compare_declines_when_a_term_is_ambiguous():
    result = admissions.dod_admissions(compare=["Kalyan", "Pune"])
    assert not result.ok
    assert result.candidates


def test_compare_needs_two_distinct_scopes():
    for terms in (["Pune"], ["Pune", "Pune"], [], ["", "  "]):
        result = admissions.dod_admissions(compare=terms) if terms else None
        if result is None:
            continue
        assert not result.ok, f"{terms} should not chart as a comparison"


def test_compare_refuses_an_unreadable_number_of_series():
    terms = ["Pune", "Nagpur", "Nashik", "Akola", "Latur", "Goa"]
    result = admissions.dod_admissions(compare=terms)
    assert not result.ok
    assert str(admissions.COMPARE_MAX) in result.decline_reason()


def test_compare_provenance_records_every_scope():
    result = admissions.dod_admissions(compare=["Maharashtra", "South"], days=5)
    description = result.provenance.describe()
    for label in result.chart.y:
        assert label in description


# ---------- separate calls, merged by the render layer ----------

def test_two_separate_calls_render_as_one_chart():
    """The logged failure: six calls produced zero charts."""
    blocks, provenance = runtime._blocks([
        admissions.dod_admissions(region="Maharashtra", days=5),
        admissions.dod_admissions(region="South", days=5)])
    assert [b.type for b in blocks] == ["chart", "table"]
    assert len(provenance) == 2, "each series keeps its own provenance line"


def test_a_merged_chart_names_each_series_by_scope():
    chart = _chart([admissions.dod_admissions(center="Pune", days=5),
                    admissions.dod_admissions(center="Nagpur", days=5)])
    assert len(chart.data["y"]) == 2
    assert any("Pune" in label for label in chart.data["y"])
    assert any("Nagpur" in label for label in chart.data["y"])


def test_merged_chart_rows_carry_every_series_key():
    """Recharts reads by dataKey; a missing key silently draws nothing for that series."""
    chart = _chart([admissions.dod_admissions(region="Maharashtra", days=5),
                    admissions.dod_admissions(region="South", days=5)])
    for row in chart.data["rows"]:
        for key in chart.data["y"]:
            assert key in row


def test_three_calls_merge_into_three_series():
    chart = _chart([admissions.dod_admissions(center=name, days=5)
                    for name in ("Pune", "Nagpur", "Nashik")])
    assert len(chart.data["y"]) == 3


def test_an_exclusion_comparison_merges_too():
    """"Mumbai vs the rest of Maharashtra" cannot use compare, so this path must work."""
    chart = _chart([admissions.dod_admissions(center="Mumbai", days=5),
                    admissions.dod_admissions(region="Maharashtra", exclude="Mumbai",
                                              days=5)])
    assert len(chart.data["y"]) == 2
    assert any("excluding" in label for label in chart.data["y"])


def test_a_single_result_is_unchanged_by_the_merge_path():
    blocks, _ = runtime._blocks([admissions.dod_admissions(region="Maharashtra", days=5)])
    chart = next(b for b in blocks if b.type == "chart")
    assert chart.data["y"] == ["Admissions"]
    assert [b.type for b in blocks] == ["chart", "table"]


def test_different_metrics_are_not_merged():
    """Days and months share no axis; merging them would invent one."""
    blocks, _ = runtime._blocks([
        admissions.dod_admissions(region="Maharashtra", days=5),
        admissions.monthly_trend(region="Maharashtra", months=3)])
    assert [b.type for b in blocks] == ["chart", "table", "chart", "table"]


def test_an_identical_call_twice_is_deduped_not_merged():
    result = admissions.dod_admissions(region="Maharashtra", days=5)
    blocks, _ = runtime._blocks([result, result])
    chart = next(b for b in blocks if b.type == "chart")
    assert chart.data["y"] == ["Admissions"]


def test_an_already_merged_result_passes_through_untouched():
    compared = admissions.dod_admissions(compare=["Maharashtra", "South"], days=5)
    blocks, _ = runtime._blocks([compared])
    chart = next(b for b in blocks if b.type == "chart")
    assert chart.data["y"] == compared.chart.y


def test_totals_stay_out_of_a_merged_chart():
    """Center rollups carry a Subtotal row that would dwarf every real bar."""
    merged = series.merge([rollups.center_rollup("registrations"),
                           rollups.center_rollup("registrations", region="Maharashtra")])
    assert merged is not None
    labels = [str(row[0]).lower() for row in merged.rows]
    assert labels, "the merge must keep the real center rows"
    assert not any(label in series.TOTAL_LABELS for label in labels)


def test_the_same_scope_measured_two_ways_is_not_merged():
    """Registrations and this month's admissions differ by an order of magnitude; one
    axis would flatten the smaller series into the baseline."""
    assert series.merge([rollups.region_rollup("registrations"),
                         rollups.region_rollup("monthly_admissions")]) is None


def test_series_with_no_shared_axis_values_are_not_merged():
    """Two region leaderboards share no centers, so one chart would be two disjoint halves."""
    assert series.merge([rollups.center_rollup("registrations", region="Maharashtra"),
                         rollups.center_rollup("registrations", region="South")]) is None


def test_scalar_results_are_never_merged():
    blocks, provenance = runtime._blocks([revenue.arpu(), revenue.arpu(region="South")])
    assert blocks == []
    assert len(provenance) == 2


# ---------- the pivot itself ----------

def test_unequal_windows_interleave_instead_of_appending():
    """A shorter window appended after a longer one would draw a line running backwards."""
    merged = series.merge([admissions.dod_admissions(region="Maharashtra", days=3),
                           admissions.dod_admissions(region="South", days=6)])
    dates = [row[0] for row in merged.rows]
    assert dates == sorted(dates), "dates must stay chronological across both series"
    assert len(dates) == 6


def test_a_gap_is_none_rather_than_zero():
    """A zero would read as "no admissions"; None reads as "not measured"."""
    merged = series.merge([admissions.dod_admissions(region="Maharashtra", days=3),
                           admissions.dod_admissions(region="South", days=6)])
    assert merged.rows[0][1] is None
    assert merged.rows[0][2] is not None


def test_equal_windows_keep_the_original_order():
    alone = admissions.dod_admissions(region="Maharashtra", days=5)
    merged = series.merge([alone, admissions.dod_admissions(region="South", days=5)])
    assert [row[0] for row in merged.rows] == [row[0] for row in alone.rows]


def test_classwise_order_survives_a_merge():
    alone = admissions.classwise_breakdown(center="Pune")
    merged = series.merge([alone, admissions.classwise_breakdown(center="Nagpur")])
    assert [row[0] for row in merged.rows] == [row[0] for row in alone.rows]


def test_merge_refuses_a_single_result():
    assert series.merge([admissions.dod_admissions(region="Maharashtra", days=5)]) is None


def test_merge_refuses_mismatched_metrics():
    assert series.merge([admissions.dod_admissions(region="Maharashtra", days=5),
                         admissions.monthly_trend(region="Maharashtra", months=3)]) is None


def test_merge_refuses_duplicate_series_names():
    """Two identical scopes would collapse into one column and lose a series."""
    result = admissions.dod_admissions(region="Maharashtra", days=5)
    assert series.merge([result, result]) is None


def test_merge_refuses_a_declined_result():
    assert series.merge([admissions.dod_admissions(region="Maharashtra", days=5),
                         admissions.dod_admissions(center="Atlantis")]) is None


def test_merged_totals_match_the_series_sums():
    results = [admissions.dod_admissions(region=name, days=5)
               for name in ("Maharashtra", "South")]
    merged = series.merge(results)
    for label, source in zip(merged.chart.y, results):
        assert merged.values["totals"][label] == source.values["value"]
