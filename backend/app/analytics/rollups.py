"""Roll-ups that mirror the sheet's subtotal and grand-total rows.

Daily_tracker rows 5/30/34/48 are region subtotals and row 49 is their sum. Counts
roll up by addition; ARPU is a per-student rate and rolls up by re-averaging over the
wider population rather than by averaging the center averages.
"""
from __future__ import annotations

from ..data import registry
from ..data.schema import TABLE_RD26
from . import admissions, cancellations, finance, retention, revenue
from .query import fmt_int, pct, provenance, require
from .result import ChartSpec, ToolResult

# Metrics that can be rolled up, and how.
_METRICS = {
    "registrations": (admissions.fresh_registrations, "sum", "Registrations"),
    "monthly_admissions": (admissions.monthly_admissions, "sum", "Admissions this month"),
    "classwise": (admissions.classwise_breakdown, "sum", "Class-wise registrations"),
    "first_emi": (finance.first_emi, "sum", "1st EMI paid"),
    "autopay": (finance.autopay, "sum", "Auto-pay active"),
    "second_emi": (finance.second_emi, "sum", "2nd EMI paid"),
    "senior_retention": (retention.senior_retention, "sum", "Seniors retained"),
    "cancellations": (cancellations.cancellations, "sum", "Cancellations"),
    "arpu": (revenue.arpu, "rate", "ARPU"),
}

METRIC_NAMES = tuple(_METRICS)


def _resolve_metric(metric_name: str):
    key = (metric_name or "registrations").strip().lower()
    aliases = {"admissions": "registrations", "fresh_registrations": "registrations",
               "monthly": "monthly_admissions", "retention": "senior_retention",
               "churn": "cancellations", "revenue": "arpu"}
    return _METRICS.get(aliases.get(key, key)), aliases.get(key, key)


def region_rollup(metric_name: str = "registrations") -> ToolResult:
    """One row per region plus a grand total. Daily_tracker rows 5/30/34/48 and 49."""
    metric = "region_rollup"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked

    entry, key = _resolve_metric(metric_name)
    if entry is None:
        return ToolResult.unavailable(
            metric, f"{metric_name!r} cannot be rolled up. Available: "
                    f"{', '.join(METRIC_NAMES)}")
    fn, mode, label = entry

    rows: list[list[object]] = []
    total = 0.0
    weight = 0
    problems: list[str] = []
    for region in registry.all_regions():
        result = fn(region=region)
        if not result.ok:
            problems.append(f"{region}: {result.unavailable_reason or result.clarification}")
            rows.append([region, None])
            continue
        value = result.values.get("value")
        rows.append([region, _round(value)])
        if value is None:
            continue
        if mode == "sum":
            total += float(value)
        else:
            students = int(result.values.get("students") or 0)
            total += float(value) * students
            weight += students

    if mode == "sum":
        grand: float | None = total
    else:
        grand = (total / weight) if weight else None
    rows.append(["Grand Total", _round(grand)])

    if all(r[1] is None for r in rows[:-1]):
        return ToolResult.unavailable(
            metric, problems[0] if problems else f"no data for {label}")

    return ToolResult(
        metric=metric,
        summary=(f"{label} by region — grand total "
                 f"{fmt_int(grand) if mode == 'sum' else _round(grand)}."),
        values={"value": _round(grand), "metric": key, "regions": len(rows) - 1},
        columns=["Region", label],
        rows=rows,
        chart=ChartSpec(kind="bar", x="Region", y=[label],
                        title=f"{label} by region"),
        provenance=provenance(
            metric, [TABLE_RD26], [], None, row_count=len(rows) - 1,
            notes=[f"{label} rolled up by {'addition' if mode == 'sum' else 'weighted average'}"]
                  + problems),
    )


def center_rollup(metric_name: str = "registrations",
                  region: str | None = None) -> ToolResult:
    """One row per center, highest first, with a subtotal."""
    metric = "center_rollup"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked

    entry, key = _resolve_metric(metric_name)
    if entry is None:
        return ToolResult.unavailable(
            metric, f"{metric_name!r} cannot be rolled up. Available: "
                    f"{', '.join(METRIC_NAMES)}")
    fn, mode, label = entry

    if region:
        from .filters import resolve_scope
        scope = resolve_scope(region=region)
        if not scope.ok:
            return ToolResult.needs_clarification(
                metric, scope.clarification or "", scope.candidates)
        centers = registry.centers_in_region(scope.region) if scope.region else []
        scope_label = scope.describe()
    else:
        centers = registry.all_centers()
        scope_label = "all centers"

    rows: list[list[object]] = []
    total = 0.0
    weight = 0
    for center in centers:
        result = fn(center=center)
        if not result.ok:
            continue
        value = result.values.get("value")
        if value is None:
            continue
        rows.append([center, _round(value)])
        if mode == "sum":
            total += float(value)
        else:
            students = int(result.values.get("students") or 0)
            total += float(value) * students
            weight += students

    if not rows:
        return ToolResult.unavailable(metric, f"no {label} data for {scope_label}")

    rows.sort(key=lambda r: float(r[1] or 0), reverse=True)
    subtotal = total if mode == "sum" else ((total / weight) if weight else None)
    rows.append(["Subtotal", _round(subtotal)])

    return ToolResult(
        metric=metric,
        summary=(f"{label} for {len(rows) - 1} centers in {scope_label}; highest is "
                 f"{rows[0][0]} at {rows[0][1]}."),
        values={"value": _round(subtotal), "metric": key, "top_center": rows[0][0],
                "top_value": rows[0][1], "scope": scope_label},
        columns=["Center", label],
        rows=rows,
        chart=ChartSpec(kind="bar", x="Center", y=[label],
                        title=f"{label} by center — {scope_label}"),
        provenance=provenance(metric, [TABLE_RD26], [], None, row_count=len(rows) - 1),
    )


def target_scoreboard() -> ToolResult:
    """Registration and monthly achievement per region, against target."""
    metric = "target_scoreboard"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked

    rows: list[list[object]] = []
    for region in registry.all_regions():
        total = admissions.fresh_registrations(region=region)
        monthly = admissions.monthly_admissions(region=region)
        if not total.ok:
            continue
        rows.append([
            region,
            total.values.get("value"),
            _round(total.values.get("target")),
            _pctstr(total.values.get("achieved_pct")),
            monthly.values.get("value") if monthly.ok else None,
            _round(monthly.values.get("target")) if monthly.ok else None,
            _pctstr(monthly.values.get("achieved_pct")) if monthly.ok else None,
        ])

    if not rows:
        return ToolResult.unavailable(metric, "no regions are loaded")
    if all(r[2] is None for r in rows):
        return ToolResult.unavailable(
            metric, "targets are not loaded, so achievement cannot be scored")

    return ToolResult(
        metric=metric,
        summary=f"Target achievement across {len(rows)} regions.",
        values={"regions": len(rows)},
        columns=["Region", "Registrations", "Reg target", "Reg %",
                 "This month", "Month target", "Month %"],
        rows=rows,
        provenance=provenance(metric, [TABLE_RD26], [], None, row_count=len(rows)),
    )


def _round(value: object) -> object:
    """Counts stay integers; rates keep two decimals."""
    if value is None:
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 2)
    return value


def _pctstr(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:.1f}%"
