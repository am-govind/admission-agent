"""Synthetic sample source, selected only by DATA_SOURCE=sample.

Lets the whole app and the test suite run with no credentials and no workbook. It is
never a fallback: if a real source is configured and fails, the refresh fails, because
answering a finance question with invented numbers is worse than declining.

Distributions mirror the shape of the real AY2026 dump (values, categories and
proportions) so metrics come out non-degenerate.
"""
from __future__ import annotations

import datetime as dt
import random
from typing import Any, Sequence

from ..schema import (CLASSES, ELIGIBILITY_STATUSES, EP_STATUSES, FORM_STATUSES,
                      PAYMENT_MILESTONES, RD_COLUMNS, REGIONS_CENTERS, TABLE_FINANCE,
                      TABLE_RD25, TABLE_RD26, TABLE_TARGETS)
from .base import SheetSource, TableRead

_FINANCE_COLUMNS = ["region", "batch", "center", "status", "newpayment_checks",
                    "vp_ps_regular_schemes"]
_TARGETS_COLUMNS = ["region", "center", "class_course", "reg_target",
                    "retention_target", "monthly_target", "arpu_target"]

_CENTER_REGION = {c: r for r, cs in REGIONS_CENTERS.items() for c in cs}


def _rd_rows(academic_year: int, count: int, seed: int) -> list[list[Any]]:
    rng = random.Random(seed)
    start = dt.date(academic_year - 1, 12, 20)
    end = dt.date(academic_year, 7, 26)
    span = (end - start).days
    centers = list(_CENTER_REGION)
    rows: list[list[Any]] = []

    for i in range(count):
        center = rng.choice(centers)
        region = _CENTER_REGION[center]
        free = rng.random() < 0.008
        milestone = rng.choices(
            PAYMENT_MILESTONES, weights=[4, 6, 2, 24, 29, 1, 1, 33])[0]
        fees_amt = round(rng.uniform(6000, 180000), 2)
        if free:
            fees_paid = 0.0
        elif milestone == "Less than Token":
            fees_paid = float(rng.randint(500, 3498))
        elif milestone == "Token Only":
            fees_paid = float(rng.choice([3499, 5000, 10000, 15000]))
        else:
            frac = {"Paid btw Token & 1st EMI": 0.18, "1st EMI Paid": 0.30,
                    "2nd EMI Paid": 0.50, "3rd EMI Paid": 0.70,
                    "4th EMI Paid": 0.88, "Total Paid": 1.0}[milestone]
            fees_paid = round(fees_amt * frac, 2)
        arpu = round(fees_amt * rng.uniform(0.55, 0.95), 2)
        rows.append([
            region,
            23000000 + seed * 100000 + i,
            f"Student {i}",
            rng.choices(CLASSES, weights=[4, 10, 11, 36, 14, 8, 4, 3, 9, 1])[0],
            "No Batch" if rng.random() < 0.35 else f"B{rng.randint(1, 40)}",
            center,
            rng.choices([1, 2, 3], weights=[88, 9, 3])[0],
            start + dt.timedelta(days=rng.randint(0, span)),
            f"PW{rng.randint(10000, 99999)}",
            fees_amt,
            round(rng.uniform(0, 80), 2),
            fees_paid,
            round(100 * fees_paid / fees_amt, 2) if fees_amt else 0.0,
            milestone,
            rng.choices(ELIGIBILITY_STATUSES, weights=[84, 5, 7, 4])[0],
            rng.choices(["Active", "Inactive"], weights=[99, 1])[0],
            free,
            rng.choices(EP_STATUSES, weights=[78, 9, 6, 5, 1.6, 0.2, 0.2])[0] or None,
            rng.choices(FORM_STATUSES, weights=[89, 7, 1, 3])[0],
            arpu,
            "Yes" if rng.random() < 0.987 else "No",
        ])
    return rows


def _finance_rows(rd_rows: Sequence[Sequence[Any]], seed: int) -> list[list[Any]]:
    rng = random.Random(seed)
    idx = {name: i for i, name in enumerate(RD_COLUMNS)}
    return [
        [r[idx["region"]], r[idx["batch"]], r[idx["center"]], r[idx["status"]],
         r[idx["newpayment_checks"]], rng.random() < 0.2]
        for r in rd_rows
    ]


def _target_rows(rd_rows: Sequence[Sequence[Any]], seed: int) -> list[list[Any]]:
    """Targets sized off achieved volume so achievement percentages land near 100%."""
    rng = random.Random(seed)
    idx = {name: i for i, name in enumerate(RD_COLUMNS)}
    achieved: dict[str, int] = {}
    for r in rd_rows:
        achieved[r[idx["center"]]] = achieved.get(r[idx["center"]], 0) + 1
    rows: list[list[Any]] = []
    for center, region in _CENTER_REGION.items():
        total = achieved.get(center, 0)
        rows.append([
            region, center, "",
            max(1, int(total * rng.uniform(0.9, 1.3))),
            max(1, int(total * rng.uniform(0.05, 0.15))),
            max(1, int(total * rng.uniform(0.1, 0.25))),
            round(rng.uniform(55000, 85000), 2),
        ])
    return rows


class SampleSource(SheetSource):
    name = "sample"

    def __init__(self, rd26_rows: int = 4000, rd25_rows: int = 4200) -> None:
        self._rd26 = _rd_rows(2026, rd26_rows, seed=26)
        self._rd25 = _rd_rows(2025, rd25_rows, seed=25)
        self._tables = {
            TABLE_RD26: (RD_COLUMNS, self._rd26),
            TABLE_RD25: (RD_COLUMNS, self._rd25),
            TABLE_FINANCE: (_FINANCE_COLUMNS, _finance_rows(self._rd26, seed=7)),
            TABLE_TARGETS: (_TARGETS_COLUMNS, _target_rows(self._rd26, seed=99)),
        }

    def read_table(self, table: str) -> TableRead | None:
        entry = self._tables.get(table)
        if entry is None:
            return None
        header, rows = entry
        return TableRead(header=header, windows=[rows], tab=f"sample:{table}")
