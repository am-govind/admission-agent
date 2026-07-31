"""Admissions metrics from the Daily_tracker sheet.

Cell references point at Business_Logic_Report_DETAILED.pdf. Where a workbook formula
matches on center only (class-wise, 1st EMI) the scope filter still pins the region
too; center-to-region is one-to-one in the data, so the count is identical and the
query stays correct if that ever stops being true.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from . import series
from ..data.reference_date import (dod_dates, month_offset, month_starts, next_month,
                                   reference_date)
from ..data.schema import CLASSWISE_TOKENS, TABLE_RD26
from .filters import (ACTIVE, CONFIRMED_INCL, CONFIRMED_STRICT, NOT_FREE, ClassFilter,
                      Scope, resolve_classes, resolve_scope)
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


# More than a handful of series makes a chart unreadable, and each one is a full query.
COMPARE_MAX = 5


def compare_series(metric: str, terms: list[str],
                   build: Callable[[str], ToolResult]) -> ToolResult:
    """Run one series query per scope and pivot the results into a single chart.

    `build` is the same single-scope function the caller would otherwise have run, so a
    compared series and a standalone one are computed by identical code and cannot
    disagree.

    A term that will not resolve declines the whole call with that term's own reason.
    Dropping it instead would answer a two-scope question with one scope and no warning,
    which reads as a complete answer.
    """
    wanted = list(dict.fromkeys(t.strip() for t in terms if t and t.strip()))
    if len(wanted) < 2:
        return ToolResult.needs_clarification(
            metric, "A comparison needs at least two different centers, cities or "
                    "regions. Name the ones to compare.")
    if len(wanted) > COMPARE_MAX:
        return ToolResult.unavailable(
            metric, f"comparing more than {COMPARE_MAX} scopes at once produces an "
                    f"unreadable chart; ask for the top few, or for a ranked table")

    results: list[ToolResult] = []
    for term in wanted:
        result = build(term)
        if not result.ok:
            return result
        results.append(result)

    merged = series.merge(results)
    if merged is None:
        return ToolResult.unavailable(
            metric, f"the {metric} series for {', '.join(wanted)} could not be lined up "
                    f"on a shared axis")
    return merged


def _scoped(metric: str, center: str | None, region: str | None,
            exclude: str | None = None,
            classes: list[str] | None = None) -> tuple[Scope, ClassFilter, ToolResult | None]:
    """Resolve the scope and class filter together, or return the decline that blocks."""
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return Scope(), ClassFilter(), blocked
    scope = resolve_scope(center, region, exclude)
    if not scope.ok:
        return scope, ClassFilter(), ToolResult.needs_clarification(
            metric, scope.clarification or "", scope.candidates)
    selected = resolve_classes(classes)
    if not selected.ok:
        return scope, selected, ToolResult.needs_clarification(
            metric, selected.clarification or "",
            [label for label, _ in CLASSWISE_TOKENS])
    return scope, selected, None


def _class_note(selected: ClassFilter) -> list[str]:
    """Provenance note naming the classes counted, when they were narrowed."""
    return [f"classes {selected.label}"] if selected.requested else []


def _scope_label(scope: Scope, selected: ClassFilter) -> str:
    """Scope description including any class narrowing, for summaries and chart titles."""
    if selected.requested:
        return f"{scope.describe()} ({selected.label})"
    return scope.describe()


def fresh_registrations(center: str | None = None, region: str | None = None,
                        before: dt.date | None = None, exclude: str | None = None,
                        classes: list[str] | None = None) -> ToolResult:
    """Total confirmed fresh registrations. Daily_tracker C128 / D3, Finance C2."""
    metric = "fresh_registrations"
    scope, selected, blocked = _scoped(metric, center, region, exclude, classes)
    if blocked:
        return blocked

    clauses = [*scope.clauses, *selected.clauses, *_BASE]
    params = [*scope.params, *selected.params]
    if before is not None:
        clauses.append("joining_date < ?")
        params.append(before)
    value = count_rows(TABLE_RD26, clauses, params)

    # A target covers every class, so it cannot be compared with a filtered count.
    target = None if selected.requested else target_lookup("reg_target", scope)
    achieved = pct(value, target)  # E3 = IFERROR(D3/C3,"")

    label = _scope_label(scope, selected)
    summary = f"{fmt_int(value)} confirmed registrations for {label}"
    if target:
        summary += f" against a target of {fmt_int(target)} ({fmt_pct(achieved)} achieved)"
    return ToolResult(
        metric=metric,
        summary=summary + ".",
        values={"value": value, "target": target, "achieved_pct": achieved,
                "scope": label},
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=value,
                              notes=_class_note(selected)),
    )


def monthly_admissions(center: str | None = None, region: str | None = None,
                       months_back: int = 0, exclude: str | None = None,
                       classes: list[str] | None = None) -> ToolResult:
    """Admissions in one month. Daily_tracker J3, with L3 as the gap.

    months_back=0 is the reference month, 1 is the month before it.
    """
    metric = "monthly_admissions"
    scope, selected, blocked = _scoped(metric, center, region, exclude, classes)
    if blocked:
        return blocked

    ref = reference_date()
    start, end = month_offset(ref, months_back)
    clauses = [*scope.clauses, *selected.clauses, *_BASE,
               "joining_date >= ?", "joining_date < ?"]
    params = [*scope.params, *selected.params, start, end]
    value = count_rows(TABLE_RD26, clauses, params)

    # The monthly target is set for the current month across all classes; neither a
    # past month nor a class subset can be measured against it.
    comparable = months_back == 0 and not selected.requested
    target = target_lookup("monthly_target", scope) if comparable else None
    achieved = pct(value, target)              # K3
    pending = (target - value) if target is not None else None   # L3 = I3 - J3

    label = _scope_label(scope, selected)
    month_name = start.strftime("%B %Y")
    summary = f"{fmt_int(value)} admissions in {month_name} for {label}"
    if target:
        summary += (f" against a monthly target of {fmt_int(target)} "
                    f"({fmt_pct(achieved)} achieved, {fmt_int(pending)} still needed)")
    return ToolResult(
        metric=metric,
        summary=summary + ".",
        values={"value": value, "target": target, "achieved_pct": achieved,
                "pending": pending, "month": month_name, "scope": label},
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=value,
                              ref=ref,
                              notes=[f"month window {start} to {end}",
                                     *_class_note(selected)]),
    )


def dod_admissions(center: str | None = None, region: str | None = None,
                   days: int = 20, exclude: str | None = None,
                   classes: list[str] | None = None,
                   compare: list[str] | None = None) -> ToolResult:
    """Day-on-day admissions, newest first. Daily_tracker M3..AG3."""
    metric = "dod_admissions"
    if compare:
        return compare_series(metric, compare, lambda term: dod_admissions(
            center=term, days=days, classes=classes))

    scope, selected, blocked = _scoped(metric, center, region, exclude, classes)
    if blocked:
        return blocked

    ref = reference_date()
    calendar = dod_dates(ref, days=max(1, min(days, 90)))
    oldest, newest = calendar[-1], calendar[0]

    clauses = [*scope.clauses, *selected.clauses, *_BASE,
               "joining_date >= ?", "joining_date <= ?"]
    params = [*scope.params, *selected.params, oldest, newest]
    counts = {
        r[0]: int(r[1])
        for r in select_rows(TABLE_RD26, "joining_date, COUNT(*)", clauses, params,
                             group_by="joining_date")
    }

    rows = [[d.isoformat(), counts.get(d, 0)] for d in calendar]
    total = sum(r[1] for r in rows)
    label = _scope_label(scope, selected)
    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(total)} admissions over the last {len(calendar)} days "
                 f"for {label}, latest day {newest.isoformat()} "
                 f"with {counts.get(newest, 0)}."),
        values={"value": total, "days": len(calendar), "latest_date": newest.isoformat(),
                "latest_count": counts.get(newest, 0), "scope": label},
        columns=["Date", "Admissions"],
        # Oldest-first so the line reads left to right.
        rows=list(reversed(rows)),
        chart=ChartSpec(kind="line", x="Date", y=["Admissions"],
                        title=f"Daily admissions — {label}"),
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=total,
                              ref=ref,
                              notes=[f"{oldest} to {newest}", *_class_note(selected)]),
    )


def monthly_trend(center: str | None = None, region: str | None = None,
                  months: int = 12, exclude: str | None = None,
                  classes: list[str] | None = None,
                  compare: list[str] | None = None) -> ToolResult:
    """Month-by-month admissions. Daily_tracker D61 series."""
    metric = "monthly_trend"
    if compare:
        return compare_series(metric, compare, lambda term: monthly_trend(
            center=term, months=months, classes=classes))

    scope, selected, blocked = _scoped(metric, center, region, exclude, classes)
    if blocked:
        return blocked

    ref = reference_date()
    starts = month_starts(ref, months=max(1, min(months, 36)))
    window_start, window_end = starts[0], next_month(starts[-1])

    clauses = [*scope.clauses, *selected.clauses, *_BASE,
               "joining_date >= ?", "joining_date < ?"]
    params = [*scope.params, *selected.params, window_start, window_end]
    counts = {
        (r[0].date() if isinstance(r[0], dt.datetime) else r[0]): int(r[1])
        for r in select_rows(TABLE_RD26, "date_trunc('month', joining_date), COUNT(*)",
                             clauses, params, group_by="1")
    }

    rows = [[s.strftime("%b %Y"), counts.get(s, 0)] for s in starts]
    total = sum(r[1] for r in rows)
    label = _scope_label(scope, selected)
    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(total)} admissions across {len(starts)} months for "
                 f"{label}, ending {starts[-1].strftime('%B %Y')}."),
        values={"value": total, "months": len(starts), "scope": label},
        columns=["Month", "Admissions"],
        rows=rows,
        chart=ChartSpec(kind="line", x="Month", y=["Admissions"],
                        title=f"Monthly admissions — {label}"),
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=total,
                              ref=ref, notes=_class_note(selected)),
    )


def classwise_breakdown(center: str | None = None, region: str | None = None,
                        classes: list[str] | None = None,
                        exclude: str | None = None,
                        compare: list[str] | None = None) -> ToolResult:
    """Registrations per class/stream. Daily_tracker D128..L128.

    Uses the inclusive threshold (>= 3498), unlike the registration total, and covers
    only the workbook's nine class columns — so it does not sum to that total.
    """
    metric = "classwise_breakdown"
    if compare:
        return compare_series(metric, compare, lambda term: classwise_breakdown(
            center=term, classes=classes))

    scope, selected, blocked = _scoped(metric, center, region, exclude, classes)
    if blocked:
        return blocked

    # A column per class, so the selection drives the SELECT rather than the WHERE.
    tokens = selected.tokens
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

    class_note = (f"{len(tokens)} selected classes" if selected.requested
                  else "nine tracked classes only")
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


def pending_admissions(center: str | None = None, region: str | None = None,
                       exclude: str | None = None) -> ToolResult:
    """Gap to the monthly target. Daily_tracker L3."""
    monthly = monthly_admissions(center=center, region=region, exclude=exclude)
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


def admissions_summary(center: str | None = None, region: str | None = None,
                       exclude: str | None = None) -> ToolResult:
    """Registration, monthly and class-mix headlines in one call."""
    metric = "admissions_summary"
    total = fresh_registrations(center=center, region=region, exclude=exclude)
    if not total.ok:
        return total
    monthly = monthly_admissions(center=center, region=region, exclude=exclude)
    classwise = classwise_breakdown(center=center, region=region, exclude=exclude)

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
