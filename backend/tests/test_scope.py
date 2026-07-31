"""Scope resolution: cities, exclusions, periods and class filters.

These are the four things the tools could not express before, and each one has a wrong
answer that looks plausible. A city that silently resolves to one of its centers, or an
"excluding" question answered by subtracting two overlapping totals, produces a number
with no visible defect — so the assertions here check the arithmetic closes, not just
that a call succeeded.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.analytics import admissions
from app.analytics.filters import resolve_classes, resolve_scope
from app.data import registry
from app.data.reference_date import month_bounds, month_offset, reference_date


# ---------- city grouping ----------

def test_a_city_aggregates_its_centers():
    resolution = registry.resolve("Pune")
    assert resolution.kind == "city"
    assert len(resolution.members) > 1
    assert all(m.startswith("Pune") for m in resolution.members)


def test_a_city_scope_counts_every_center_in_it():
    """The whole point: "Pune" must be the sum of its centers, not one of them."""
    scope = resolve_scope(center="Pune")
    assert scope.ok, scope.clarification
    total = admissions.fresh_registrations(center="Pune").values["value"]
    parts = sum(admissions.fresh_registrations(center=name).values["value"]
                for name in scope.centers)
    assert total == parts


def test_a_city_scope_says_how_many_centers_it_covered():
    """Aggregating trades a question for an assumption; the label is what makes it visible."""
    scope = resolve_scope(center="Pune")
    assert scope.label == f"Pune ({len(scope.centers)} centers)"


def test_a_term_spanning_two_cities_still_asks():
    """Kalyan exists in both Dombivali and Mumbai, so it is genuinely ambiguous."""
    resolution = registry.resolve("Kalyan")
    assert resolution.kind == "ambiguous"
    assert len({registry.city_of(c) for c in resolution.candidates}) > 1

    result = admissions.fresh_registrations(center="Kalyan")
    assert not result.ok
    assert result.candidates, "an ambiguous term must offer the options"


def test_an_exact_center_name_beats_its_city():
    resolution = registry.resolve("Nagpur Vidyapeeth")
    assert resolution.kind == "center"
    assert resolution.value == "Nagpur Vidyapeeth"


def test_a_single_matching_center_is_not_a_city():
    resolution = registry.resolve("Panvel")
    assert resolution.kind == "center"


def test_an_unknown_term_is_still_unknown():
    assert registry.resolve("Atlantis").kind == "none"


def test_city_of_uses_the_segment_before_the_dash():
    assert registry.city_of("Pune - FC Road Vidyapeeth") == "Pune"
    assert registry.city_of("Nagpur Vidyapeeth") == "Nagpur"


# ---------- exclusion ----------

def test_a_part_plus_the_rest_equals_the_whole():
    """The invariant that makes "rest of" trustworthy."""
    whole = admissions.fresh_registrations(region="Maharashtra").values["value"]
    part = admissions.fresh_registrations(center="Mumbai").values["value"]
    rest = admissions.fresh_registrations(region="Maharashtra",
                                          exclude="Mumbai").values["value"]
    assert part + rest == whole
    assert 0 < part < whole, "a meaningful test needs Mumbai to be a real subset"


def test_an_exclusion_is_named_in_the_scope_label():
    result = admissions.fresh_registrations(region="Maharashtra", exclude="Mumbai")
    label = result.values["scope"]
    assert "Maharashtra" in label and "excluding Mumbai" in label


def test_excluding_a_region_leaves_the_others():
    everything = admissions.fresh_registrations().values["value"]
    south = admissions.fresh_registrations(region="South").values["value"]
    rest = admissions.fresh_registrations(exclude="South").values["value"]
    assert south + rest == everything


def test_an_unresolvable_exclusion_asks_rather_than_ignoring_it():
    """Silently ignoring it would report all of Maharashtra as though it were filtered."""
    result = admissions.fresh_registrations(region="Maharashtra", exclude="Atlantis")
    assert not result.ok
    assert result.decline_reason()


def test_excluding_an_ambiguous_term_asks():
    result = admissions.fresh_registrations(region="Maharashtra", exclude="Kalyan")
    assert not result.ok
    assert result.candidates


# ---------- periods ----------

def test_month_offset_walks_back_one_month_at_a_time():
    ref = dt.date(2026, 3, 15)
    assert month_offset(ref, 0) == (dt.date(2026, 3, 1), dt.date(2026, 4, 1))
    assert month_offset(ref, 1) == (dt.date(2026, 2, 1), dt.date(2026, 3, 1))
    assert month_offset(ref, 2) == (dt.date(2026, 1, 1), dt.date(2026, 2, 1))


def test_month_offset_crosses_a_year_boundary():
    assert month_offset(dt.date(2026, 1, 20), 1) == (dt.date(2025, 12, 1),
                                                     dt.date(2026, 1, 1))


def test_months_back_zero_is_the_reference_month():
    ref = reference_date()
    result = admissions.monthly_admissions(months_back=0)
    assert result.values["month"] == month_bounds(ref)[0].strftime("%B %Y")


def test_months_back_one_reports_the_previous_month():
    ref = reference_date()
    result = admissions.monthly_admissions(months_back=1)
    expected = month_offset(ref, 1)[0].strftime("%B %Y")
    assert result.values["month"] == expected


def test_months_back_windows_do_not_overlap():
    """Adjacent months sharing a row would double-count it in any month-on-month answer."""
    this_month = admissions.monthly_admissions(region="Maharashtra", months_back=0)
    last_month = admissions.monthly_admissions(region="Maharashtra", months_back=1)
    assert this_month.values["month"] != last_month.values["month"]
    trend = admissions.monthly_trend(region="Maharashtra", months=2)
    by_month = {row[0]: row[1] for row in trend.rows}
    for result in (this_month, last_month):
        key = dt.datetime.strptime(result.values["month"], "%B %Y").strftime("%b %Y")
        assert by_month[key] == result.values["value"]


def test_a_past_month_has_no_target():
    """Targets are set for the current month; showing one against May would be a lie."""
    assert admissions.monthly_admissions(months_back=3).values["target"] is None


# ---------- class filters ----------

def test_no_classes_means_all_nine():
    selected = resolve_classes(None)
    assert len(selected.tokens) == 9
    assert not selected.requested
    assert not selected.clauses, "an unfiltered call must add no predicate"


def test_a_class_filter_narrows_the_count():
    whole = admissions.fresh_registrations(region="Maharashtra").values["value"]
    part = admissions.fresh_registrations(region="Maharashtra",
                                          classes=["Dropper NEET"]).values["value"]
    assert 0 < part < whole


def test_class_filtered_counts_sum_to_the_classwise_breakdown():
    """One normalisation, so a filtered count and the breakdown cannot disagree."""
    breakdown = admissions.classwise_breakdown(region="Maharashtra")
    for label, count in breakdown.rows:
        filtered = admissions.classwise_breakdown(region="Maharashtra", classes=[label])
        assert filtered.rows == [[label, count]]


@pytest.mark.parametrize("fn", [
    admissions.fresh_registrations,
    admissions.monthly_admissions,
    admissions.dod_admissions,
    admissions.monthly_trend,
])
def test_every_volume_metric_accepts_classes(fn):
    result = fn(region="Maharashtra", classes=["Dropper NEET"])
    assert result.ok, result.decline_reason()
    assert "Dropper NEET" in result.values["scope"]


def test_an_unknown_class_asks_rather_than_counting_everything():
    result = admissions.fresh_registrations(classes=["13th"])
    assert not result.ok
    assert "13th" in result.decline_reason()
    assert result.candidates


def test_a_class_filtered_count_has_no_target():
    """The target covers all nine classes, so a subset cannot be measured against it."""
    result = admissions.fresh_registrations(region="Maharashtra", classes=["Dropper NEET"])
    assert result.values["target"] is None
