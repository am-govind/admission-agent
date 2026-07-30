"""Synthetic sample-data generator.

Lets the entire app run with no Google credentials. The distributions are chosen
so the metric tools return sensible, non-degenerate numbers for a demo.
"""
from __future__ import annotations

import datetime as dt
import random

from ..core.database import _lock, get_conn
from .schema import (CLASSES, PAYMENT_MILESTONES, RD_COLUMNS, RD_NUMERIC_COLUMNS,
                     REGIONS_CENTERS, TABLE_FINANCE, TABLE_RD25, TABLE_RD26, TABLE_TARGETS)


def _rand_date(start: dt.date, end: dt.date) -> dt.date:
    return start + dt.timedelta(days=random.randint(0, (end - start).days))


def _gen_rd_rows(year_ay: int, n: int, seed: int) -> list[tuple]:
    random.seed(seed)
    rows: list[tuple] = []
    start = dt.date(year_ay - 1, 4, 1)
    end = dt.date(year_ay, 7, 18)
    for i in range(n):
        region = random.choice(list(REGIONS_CENTERS))
        center = random.choice(REGIONS_CENTERS[region])
        cls = random.choice(CLASSES)
        free = random.random() < 0.06
        milestone = random.choices(PAYMENT_MILESTONES, weights=[15, 30, 20, 12, 10, 13])[0]
        fees_amt = random.choice([120000, 150000, 100000, 90000, 180000])
        if free:
            fees_paid = 0
        elif milestone == "Token Only":
            fees_paid = random.choice([1000, 2500, 3498, 3000])
        else:
            frac = {"1st EMI Paid": 0.25, "2nd EMI Paid": 0.45, "3rd EMI Paid": 0.65,
                    "4th EMI Paid": 0.85, "Total Paid": 1.0}[milestone]
            fees_paid = int(fees_amt * frac)
        status = random.choices(["Active", "Inactive"], weights=[92, 8])[0]
        form_status = random.choices(
            ["Completed", "Stage 1", "Admission Cancelled"], weights=[80, 15, 5])[0]
        ep = random.choices(["", "Active Mandate", "Disbural Pending", "Cancelled"],
                            weights=[35, 45, 10, 10])[0]
        elig = random.choices(
            ["Eligible", "Not Eligible: Incomplete Form", "Not Eligible: Both Fee & Form"],
            weights=[55, 25, 20])[0]
        arpu_val = max(0, int(fees_amt * random.uniform(0.5, 0.95)))
        rows.append((
            region, f"{year_ay}{seed}{i:06d}", f"Student {i}", cls,
            f"B{random.randint(1, 40)}" if random.random() > 0.05 else "No Batch",
            center, random.choices([1, 2, 3], weights=[70, 20, 10])[0],
            _rand_date(start, end).isoformat(),
            random.choice(["Digital", "Referral", "Walk-in", "Event"]),
            fees_amt, random.choice([0, 5, 10, 15]), fees_paid,
            round(100 * fees_paid / fees_amt, 1) if fees_amt else 0,
            milestone, elig, status, "TRUE" if free else "FALSE", ep, form_status,
            arpu_val, "yes" if arpu_val > 0 else "no",
        ))
    return rows


def _gen_finance_rows(rd26_rows: list[tuple]) -> list[tuple]:
    """Finance Dump: region, batch, center, status, newpayment_checks, vp_ps_regular_schemes."""
    out = []
    for r in rd26_rows:
        region, batch, center, status, milestone = r[0], r[4], r[5], r[15], r[13]
        scheme = "TRUE" if random.random() < 0.2 else "FALSE"
        out.append((region, batch, center, status, milestone, scheme))
    return out


def _gen_targets() -> list[tuple]:
    random.seed(99)
    rows = []
    for region, centers in REGIONS_CENTERS.items():
        for center in centers:
            rows.append((region, center, "",
                         random.choice([1200, 1500, 1860, 900]),
                         random.choice([300, 400, 500]),
                         random.choice([150, 200, 250]),
                         random.choice([65000, 70000, 72000])))
    return rows


def _create_rd_table(conn, name: str, rows: list[tuple]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {name}")
    cols = ", ".join(
        f"{c} DOUBLE" if c in RD_NUMERIC_COLUMNS else f"{c} VARCHAR" for c in RD_COLUMNS)
    conn.execute(f"CREATE TABLE {name} ({cols})")
    placeholders = ",".join(["?"] * len(RD_COLUMNS))
    conn.executemany(f"INSERT INTO {name} VALUES ({placeholders})", rows)


def load_sample_data() -> dict[str, int]:
    conn = get_conn()
    rd26 = _gen_rd_rows(2026, 4000, seed=26)
    rd25 = _gen_rd_rows(2025, 4200, seed=25)
    finance = _gen_finance_rows(rd26)
    targets = _gen_targets()
    with _lock:
        _create_rd_table(conn, TABLE_RD26, rd26)
        _create_rd_table(conn, TABLE_RD25, rd25)
        conn.execute(f"DROP TABLE IF EXISTS {TABLE_FINANCE}")
        conn.execute(
            f"CREATE TABLE {TABLE_FINANCE} (region VARCHAR, batch VARCHAR, center VARCHAR, "
            "status VARCHAR, newpayment_checks VARCHAR, vp_ps_regular_schemes VARCHAR)")
        conn.executemany(f"INSERT INTO {TABLE_FINANCE} VALUES (?,?,?,?,?,?)", finance)
        conn.execute(f"DROP TABLE IF EXISTS {TABLE_TARGETS}")
        conn.execute(
            f"CREATE TABLE {TABLE_TARGETS} (region VARCHAR, center VARCHAR, class_course VARCHAR, "
            "reg_target INTEGER, retention_target INTEGER, monthly_target INTEGER, "
            "arpu_target DOUBLE)")
        conn.executemany(f"INSERT INTO {TABLE_TARGETS} VALUES (?,?,?,?,?,?,?)", targets)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_refresh', ?)",
                     [dt.datetime.now().isoformat()])
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('source', 'sample')")
    return {TABLE_RD26: len(rd26), TABLE_RD25: len(rd25),
            TABLE_FINANCE: len(finance), TABLE_TARGETS: len(targets)}
