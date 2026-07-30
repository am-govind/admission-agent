"""Parity harness for the sealed analytics layer.

Two kinds of check:

1. Invariants that must hold for any dataset — a percentage inside 0..100, a sum of parts
   equal to its whole, a scoped count no larger than the global one. These catch the
   filter-drift that a spot-checked number would not.
2. Golden values, keyed by (metric, scope), asserted only when GOLDEN is populated from
   the real workbook. Filling that dict is the remaining step to prove agreement with the
   spreadsheet cell for cell; until then the invariants stand on their own and the
   harness runs in CI unchanged.
"""
from __future__ import annotations

import pytest

from app.analytics import (admissions, cancellations, finance, retention, revenue,
                           rollups)
from app.analytics.result import ToolResult
from app.data import registry

# (metric, scope or None) -> expected number, exported from the workbook.
GOLDEN: dict[tuple[str, str | None], float] = {}


def value(result: ToolResult, key: str = "value") -> float:
    assert result.ok, result.decline_reason()
    assert key in result.values, f"{result.metric} has no {key!r} in {list(result.values)}"
    return float(result.values[key])


# ---------- invariants ----------

def test_registrations_are_positive():
    assert value(admissions.fresh_registrations()) > 0


def test_month_to_date_cannot_exceed_all_time():
    assert value(admissions.monthly_admissions()) <= value(admissions.fresh_registrations())


def test_center_scope_narrows_the_count():
    center = registry.all_centers()[0]
    scoped = value(admissions.fresh_registrations(center=center))
    assert 0 <= scoped <= value(admissions.fresh_registrations())


def test_region_totals_do_not_exceed_the_whole():
    result = rollups.region_rollup("registrations")
    assert result.ok
    index = result.columns.index("Registrations")
    rows = [r for r in result.rows if str(r[0]).lower() != "grand total"]
    assert sum(int(r[index]) for r in rows) <= value(admissions.fresh_registrations())


def test_classwise_parts_sum_to_the_whole():
    result = admissions.classwise_breakdown()
    assert result.ok
    index = result.columns.index("Registrations")
    rows = [r for r in result.rows if str(r[0]).lower() not in {"grand total", "total"}]
    assert sum(int(r[index]) for r in rows) == value(result)


@pytest.mark.parametrize("factory", [
    finance.first_emi, finance.autopay, finance.loan_eligibility, finance.second_emi,
    retention.senior_retention_pct, cancellations.cancellations,
])
def test_ratios_stay_fractions_between_zero_and_one(factory):
    """The workbook stores IFERROR(a/b) fractions; a 0..100 value would render as 8300%."""
    result = factory()
    if not result.ok:
        pytest.skip(result.unavailable_reason or "metric unavailable in this dataset")
    # For a metric that *is* a percentage, the ratio is the headline `value`.
    ratio_keys = {"rate"} | ({"value"} if result.metric.endswith("_pct") else set())
    ratios = {k: v for k, v in result.values.items()
              if (k in ratio_keys or k.endswith("_pct")) and isinstance(v, (int, float))}
    assert ratios, f"{result.metric} reports no ratio"
    for key, ratio in ratios.items():
        assert 0.0 <= ratio <= 1.0, f"{result.metric}.{key} = {ratio}"


def test_ratio_matches_its_own_numerator_and_denominator():
    for factory in (finance.first_emi, finance.autopay, cancellations.cancellations):
        result = factory()
        assert result.ok
        expected = result.values["value"] / result.values["base"]
        assert abs(result.values["rate"] - expected) < 1e-9, result.metric


def test_second_emi_gap_is_consistent():
    result = finance.second_emi()
    if not result.ok:
        pytest.skip(result.unavailable_reason or "finance dump not loaded")
    assert result.values["delta"] == result.values["base"] - result.values["paid"]


def test_arpu_is_plausible():
    result = revenue.arpu()
    assert result.ok
    assert 0 < value(result) < 10_000_000


def test_revenue_crores_follows_from_arpu_and_students():
    result = revenue.arpu()
    assert result.ok
    expected = result.values["value"] * result.values["students"] / 1e7
    assert abs(result.values["revenue_crores"] - expected) < 0.02


def test_unavailable_metrics_explain_themselves():
    """A missing source must produce a reason, never a zero that reads as a real figure."""
    for result in (finance.second_emi(), retention.senior_retention(),
                   revenue.revenue_estimate()):
        if not result.ok:
            assert result.unavailable_reason or result.clarification


def test_every_ok_result_carries_provenance():
    for result in (admissions.fresh_registrations(), revenue.arpu(),
                   cancellations.cancellations(), admissions.classwise_breakdown()):
        assert result.ok and result.provenance is not None
        assert result.provenance.reference_date, f"{result.metric} has no reference date"
        assert result.provenance.source_tables, f"{result.metric} names no source table"


def test_unknown_center_asks_for_clarification():
    result = admissions.fresh_registrations(center="Atlantis")
    assert not result.ok
    assert result.clarification


def test_ambiguous_center_offers_candidates():
    result = admissions.fresh_registrations(center="Mumbai")
    if result.clarification:
        assert result.candidates, "an ambiguous center must list the options"


# ---------- golden values ----------

@pytest.mark.skipif(not GOLDEN, reason="no workbook golden values exported yet")
def test_golden_values():
    lookup = {
        "fresh_registrations": lambda scope: admissions.fresh_registrations(center=scope),
        "monthly_admissions": lambda scope: admissions.monthly_admissions(center=scope),
        "first_emi": lambda scope: finance.first_emi(center=scope),
        "autopay": lambda scope: finance.autopay(center=scope),
        "second_emi": lambda scope: finance.second_emi(center=scope),
        "senior_retention": lambda scope: retention.senior_retention(center=scope),
        "cancellations": lambda scope: cancellations.cancellations(center=scope),
        "arpu": lambda scope: revenue.arpu(center=scope),
    }
    mismatches = []
    for (metric, scope), expected in GOLDEN.items():
        actual = value(lookup[metric](scope))
        if abs(actual - expected) > max(0.5, abs(expected) * 0.001):
            mismatches.append(f"{metric}/{scope or 'all'}: expected {expected}, got {actual}")
    assert not mismatches, "; ".join(mismatches)
