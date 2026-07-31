"""Admissions metrics from the Daily_tracker sheet.

Cell references point at Business_Logic_Report_DETAILED.pdf. Where a workbook formula
matches on center only (class-wise, 1st EMI) the scope filter still pins the region
too; center-to-region is one-to-one in the data, so the count is identical and the
query stays correct if that ever stops being true.
"""
from __future__ import annotations

import datetime as dt

from ..data.reference_date import (dod_dates, month_bounds, month_starts, next_month,
                                   reference_date)
from ..data.schema import CLASSWISE_TOKENS, TABLE_RD26
from .filters import ACTIVE, CONFIRMED_INCL, CONFIRMED_STRICT, NOT_FREE, Scope, resolve_scope
from .query import (count_rows, fmt_int, fmt_pct, pct, provenance, require, select_rows,
                    target_lookup)
from .result import ChartSpec, ToolResult

_BASE = [CONFIRMED_STRICT, NOT_FREE, ACTIVE]


def confirmed_count(scope: Scope, before: dt.date | None = None) -> int:
    """The confirmed-registration count every sheet uses as its denominator.

    Daily_tracker C128 (no date filter) and C61/D3 (cutoff variant).
    """
    clauses = [*scope.clauses, *_BASE]
    params = [*scope.params]
    if before is not None:
        clauses.append("joining_date < ?")
        params.append(before)
    return count_rows(TABLE_RD26, clauses, params)


def _scoped(metric: str, center: str | None, region: str | None) -> tuple[Scope, ToolResult | None]:
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return Scope(), blocked
    scope = resolve_scope(center, region)
    if not scope.ok:
        return scope, ToolResult.needs_clarification(
            metric, scope.clarification or "", scope.candidates)
    return scope, None


def fresh_registrations(center: str | None = None, region: str | None = None,
                        before: dt.date | None = None) -> ToolResult:
    """Total confirmed fresh registrations. Daily_tracker C128 / D3, Finance C2."""
    metric = "fresh_registrations"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    value = confirmed_count(scope, before=before)
    target = target_lookup("reg_target", scope)
    achieved = pct(value, target)  # E3 = IFERROR(D3/C3,"")

    clauses = [*scope.clauses, *_BASE]
    if before is not None:
        clauses.append("joining_date < ?")

    summary = f"{fmt_int(value)} confirmed registrations for {scope.describe()}"
    if target:
        summary += f" against a target of {fmt_int(target)} ({fmt_pct(achieved)} achieved)"
    return ToolResult(
        metric=metric,
        summary=summary + ".",
        values={"value": value, "target": target, "achieved_pct": achieved,
                "scope": scope.describe()},
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=value),
    )


def monthly_admissions(center: str | None = None, region: str | None = None) -> ToolResult:
    """Admissions in the reference month. Daily_tracker J3, with L3 as the gap."""
    metric = "monthly_admissions"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    ref = reference_date()
    start, end = month_bounds(ref)
    clauses = [*scope.clauses, *_BASE, "joining_date >= ?", "joining_date < ?"]
    params = [*scope.params, start, end]
    value = count_rows(TABLE_RD26, clauses, params)

    target = target_lookup("monthly_target", scope)
    achieved = pct(value, target)              # K3
    pending = (target - value) if target is not None else None   # L3 = I3 - J3

    summary = (f"{fmt_int(value)} admissions in {start.strftime('%B %Y')} "
               f"for {scope.describe()}")
    if target:
        summary += (f" against a monthly target of {fmt_int(target)} "
                    f"({fmt_pct(achieved)} achieved, {fmt_int(pending)} still needed)")
    return ToolResult(
        metric=metric,
        summary=summary + ".",
        values={"value": value, "target": target, "achieved_pct": achieved,
                "pending": pending, "month": start.strftime("%B %Y"),
                "scope": scope.describe()},
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=value,
                              ref=ref, notes=[f"month window {start} to {end}"]),
    )


def dod_admissions(center: str | None = None, region: str | None = None,
                   days: int = 20) -> ToolResult:
    """Day-on-day admissions, newest first. Daily_tracker M3..AG3."""
    metric = "dod_admissions"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    ref = reference_date()
    calendar = dod_dates(ref, days=max(1, min(days, 90)))
    oldest, newest = calendar[-1], calendar[0]

    clauses = [*scope.clauses, *_BASE, "joining_date >= ?", "joining_date <= ?"]
    params = [*scope.params, oldest, newest]
    counts = {
        r[0]: int(r[1])
        for r in select_rows(TABLE_RD26, "joining_date, COUNT(*)", clauses, params,
                             group_by="joining_date")
    }

    rows = [[d.isoformat(), counts.get(d, 0)] for d in calendar]
    total = sum(r[1] for r in rows)
    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(total)} admissions over the last {len(calendar)} days "
                 f"for {scope.describe()}, latest day {newest.isoformat()} "
                 f"with {counts.get(newest, 0)}."),
        values={"value": total, "days": len(calendar), "latest_date": newest.isoformat(),
                "latest_count": counts.get(newest, 0), "scope": scope.describe()},
        columns=["Date", "Admissions"],
        # Oldest-first so the line reads left to right.
        rows=list(reversed(rows)),
        chart=ChartSpec(kind="line", x="Date", y=["Admissions"],
                        title=f"Daily admissions — {scope.describe()}"),
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=total,
                              ref=ref, notes=[f"{oldest} to {newest}"]),
    )


def monthly_trend(center: str | None = None, region: str | None = None,
                  months: int = 12) -> ToolResult:
    """Month-by-month admissions. Daily_tracker D61 series."""
    metric = "monthly_trend"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    ref = reference_date()
    starts = month_starts(ref, months=max(1, min(months, 36)))
    window_start, window_end = starts[0], next_month(starts[-1])

    clauses = [*scope.clauses, *_BASE, "joining_date >= ?", "joining_date < ?"]
    params = [*scope.params, window_start, window_end]
    counts = {
        (r[0].date() if isinstance(r[0], dt.datetime) else r[0]): int(r[1])
        for r in select_rows(TABLE_RD26, "date_trunc('month', joining_date), COUNT(*)",
                             clauses, params, group_by="1")
    }

    rows = [[s.strftime("%b %Y"), counts.get(s, 0)] for s in starts]
    total = sum(r[1] for r in rows)
    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(total)} admissions across {len(starts)} months for "
                 f"{scope.describe()}, ending {starts[-1].strftime('%B %Y')}."),
        values={"value": total, "months": len(starts), "scope": scope.describe()},
        columns=["Month", "Admissions"],
        rows=rows,
        chart=ChartSpec(kind="line", x="Month", y=["Admissions"],
                        title=f"Monthly admissions — {scope.describe()}"),
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=total,
                              ref=ref),
    )


def classwise_breakdown(center: str | None = None, region: str | None = None,
                        classes: list[str] | None = None) -> ToolResult:
    """Registrations per class/stream. Daily_tracker D128..L128.

    Uses the inclusive threshold (>= 3498), unlike the registration total, and covers
    only the workbook's nine class columns — so it does not sum to that total.
    """
    metric = "classwise_breakdown"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    # Filter to requested classes, or use all nine.
    if classes:
        # Normalise user input to match the canonical labels.
        requested = {c.strip().lower() for c in classes}
        tokens = [t for t in CLASSWISE_TOKENS if t[0].lower() in requested]
        if not tokens:
            return ToolResult.needs_clarification(
                metric,
                f"None of {classes} matched a tracked class. "
                f"Valid classes: {', '.join(label for label, _ in CLASSWISE_TOKENS)}.",
                [label for label, _ in CLASSWISE_TOKENS])
    else:
        tokens = list(CLASSWISE_TOKENS)

    clauses = [*scope.clauses, CONFIRMED_INCL, NOT_FREE, ACTIVE]
    params = [*scope.params]
    # One pass with a CASE per class beats nine separate COUNTIFS round trips.
    select = ", ".join(
        f"SUM(CASE WHEN class_course ILIKE ? THEN 1 ELSE 0 END)" for _ in tokens)
    pattern_params = [f"%{token}%" for _, token in tokens]
    result = select_rows(TABLE_RD26, select, clauses, [*pattern_params, *params])

    counts = [int(v or 0) for v in (result[0] if result else [0] * len(tokens))]
    rows = [[label, count] for (label, _), count in zip(tokens, counts)]
    total = sum(counts)
    top = max(rows, key=lambda r: r[1]) if rows else ["n/a", 0]

    class_note = f"{len(tokens)} selected classes" if classes else "nine tracked classes only"
    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(total)} registrations across {class_note} for "
                 f"{scope.describe()}; largest is {top[0]} with {fmt_int(top[1])}."),
        values={"value": total, "largest_class": top[0], "largest_count": top[1],
                "scope": scope.describe()},
        columns=["Class", "Registrations"],
        rows=rows,
        chart=ChartSpec(kind="bar", x="Class", y=["Registrations"],
                        title=f"Class-wise registrations — {scope.describe()}"),
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=total,
                              notes=[class_note]),
    )


def pending_admissions(center: str | None = None, region: str | None = None) -> ToolResult:
    """Gap to the monthly target. Daily_tracker L3."""
    monthly = monthly_admissions(center=center, region=region)
    if not monthly.ok:
        return monthly
    target = monthly.values.get("target")
    if target is None:
        return ToolResult.unavailable(
            "pending_admissions",
            "monthly targets are not loaded, so the gap to target cannot be computed")
    pending = monthly.values.get("pending")
    verb = "still needed" if (pending or 0) > 0 else "over target"
    return ToolResult(
        metric="pending_admissions",
        summary=(f"{fmt_int(abs(pending or 0))} admissions {verb} for "
                 f"{monthly.values.get('scope')} in {monthly.values.get('month')}."),
        values={"value": pending, "target": target,
                "achieved": monthly.values.get("value"),
                "scope": monthly.values.get("scope")},
        provenance=monthly.provenance,
    )


def admissions_summary(center: str | None = None, region: str | None = None) -> ToolResult:
    """Registration, monthly and class-mix headlines in one call."""
    metric = "admissions_summary"
    total = fresh_registrations(center=center, region=region)
    if not total.ok:
        return total
    monthly = monthly_admissions(center=center, region=region)
    classwise = classwise_breakdown(center=center, region=region)

    scope_label = total.values.get("scope")
    rows = [
        ["Confirmed registrations", total.values.get("value")],
        ["Registration target", total.values.get("target")],
        ["Registration achieved %", _as_pct(total.values.get("achieved_pct"))],
        [f"Admissions in {monthly.values.get('month')}", monthly.values.get("value")],
        ["Monthly target", monthly.values.get("target")],
        ["Monthly achieved %", _as_pct(monthly.values.get("achieved_pct"))],
        ["Pending vs monthly target", monthly.values.get("pending")],
        ["Largest class", classwise.values.get("largest_class")],
    ]
    return ToolResult(
        metric=metric,
        summary=f"Admissions summary for {scope_label}.",
        values={"registrations": total.values.get("value"),
                "monthly": monthly.values.get("value"),
                "scope": scope_label},
        columns=["Measure", "Value"],
        rows=rows,
        provenance=total.provenance,
    )


def _as_pct(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:.1f}%"
