"""Cancellation metrics from the Admission Cancelled sheet."""
from __future__ import annotations

from ..core.database import execute
from ..data.schema import TABLE_RD26
from . import admissions
from .filters import CANCELLED, Scope, resolve_scope
from .query import count_rows, fmt_int, fmt_pct, pct, provenance, require
from .result import ChartSpec, ToolResult

# D2 = COUNTIFS(RD26_DUMP!F:F, B2, RD26_DUMP!S:S, "Admission Cancelled").
# Center only. Unlike every other metric it does NOT filter free admissions, active
# status or the fee threshold — the PDF flags this explicitly. The denominator C2
# does apply all three, so the rate mixes two populations. That is what the sheet
# publishes, and parity with the sheet is the requirement.
_NOTE = ("cancellation count applies no free/active/fee filters, matching the sheet; "
         "the registration denominator does apply them")


def cancellations(center: str | None = None, region: str | None = None) -> ToolResult:
    """Cancelled admissions and churn rate. Admission Cancelled C2, D2, E2."""
    metric = "cancellations"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked
    scope = resolve_scope(center, region)
    if not scope.ok:
        return ToolResult.needs_clarification(
            metric, scope.clarification or "", scope.candidates)

    clauses = [*scope.clauses, CANCELLED]
    value = count_rows(TABLE_RD26, clauses, scope.params)
    base = admissions.confirmed_count(scope)
    rate = pct(value, base)

    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(value)} cancelled admissions at {scope.describe()} against "
                 f"{fmt_int(base)} confirmed registrations — a churn rate of "
                 f"{fmt_pct(rate)}."),
        values={"value": value, "base": base, "rate": rate, "scope": scope.describe()},
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=value,
                              notes=[_NOTE]),
    )


def cancellations_by_center(region: str | None = None, limit: int = 15) -> ToolResult:
    """Cancellations per center, highest churn first."""
    metric = "cancellations_by_center"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked

    scope = Scope(label="all centers")
    scope_clauses: list[str] = []
    params: list[object] = []
    if region:
        scope = resolve_scope(region=region)
        if not scope.ok:
            return ToolResult.needs_clarification(
                metric, scope.clarification or "", scope.candidates)
        scope_clauses = list(scope.clauses)
        params = list(scope.params)

    from .filters import ACTIVE, CONFIRMED_STRICT, NOT_FREE
    base_where = " AND ".join([*scope_clauses, CONFIRMED_STRICT, NOT_FREE, ACTIVE])
    cancel_where = " AND ".join([*scope_clauses, CANCELLED])

    base_rows = {r[0]: int(r[1]) for r in execute(
        f"SELECT center, COUNT(*) FROM {TABLE_RD26} WHERE {base_where} GROUP BY center",
        params)}
    cancel_rows = {r[0]: int(r[1]) for r in execute(
        f"SELECT center, COUNT(*) FROM {TABLE_RD26} WHERE {cancel_where} GROUP BY center",
        params)}

    table: list[list[object]] = []
    for name in sorted(set(base_rows) | set(cancel_rows)):
        cancelled = cancel_rows.get(name, 0)
        base = base_rows.get(name, 0)
        rate = pct(cancelled, base)
        table.append([name, cancelled, base,
                      None if rate is None else round(rate * 100, 2)])
    table.sort(key=lambda r: (r[3] is None, -(r[3] or 0)))
    top = table[:max(1, min(limit, 53))]

    if not top:
        return ToolResult.unavailable(metric, f"no centers matched {scope.describe()}")
    return ToolResult(
        metric=metric,
        summary=(f"Highest churn for {scope.describe()} is {top[0][0]} at "
                 f"{top[0][3]}% ({top[0][1]} cancellations)."),
        values={"worst_center": top[0][0], "worst_rate_pct": top[0][3],
                "scope": scope.describe()},
        columns=["Center", "Cancelled", "Registrations", "Churn %"],
        rows=top,
        chart=ChartSpec(kind="bar", x="Center", y=["Churn %"],
                        title=f"Churn rate by center — {scope.describe()}"),
        provenance=provenance(metric, [TABLE_RD26], [CANCELLED], scope,
                              row_count=len(table), notes=[_NOTE]),
    )
