"""Golden-parity harness (stub).

Purpose: assert each sealed analytics function equals the spreadsheet's own computed
values, per center/metric, on the same-day dump. Wire real golden values once the
actual Export/Daily_tracker/Finance rows are available (see DESIGN.md §7 Phase 4).

For now this validates internal invariants against the synthetic sample data so the
harness is runnable in CI.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analytics import admissions, cancellations, finance  # noqa: E402
from app.data.sample_data import load_sample_data  # noqa: E402


def setup_module(module):  # noqa: D401
    load_sample_data()


def test_fresh_registrations_nonnegative():
    assert admissions.fresh_registrations().extra["value"] >= 0


def test_monthly_le_total():
    total = admissions.fresh_registrations().extra["value"]
    monthly = admissions.monthly_admissions().extra["value"]
    assert monthly <= total, "month-to-date admissions cannot exceed all-time registrations"


def test_cancellation_rate_bounds():
    r = cancellations.cancellations()
    assert 0.0 <= r.extra["rate"] <= 1.5


def test_classwise_sums_reasonably():
    r = admissions.classwise_breakdown()
    assert r.table is not None
    assert sum(row[1] for row in r.table["rows"]) >= 0


def test_second_emi_gap_consistent():
    r = finance.second_emi()
    assert r.extra["delta"] == r.extra["base"] - r.extra["paid"]


# TODO(parity): load golden values exported from the real workbook and assert
# equality per (center, metric); on mismatch, emit log + email alert.
