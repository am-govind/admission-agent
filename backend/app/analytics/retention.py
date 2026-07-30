"""Senior retention from the Daily_tracker sheet.

Reads LAST year's dump (rd25), not this year's: retention asks which AY2025 seniors
who had paid most or all of their fees are still active.
"""
from __future__ import annotations

from ..data.schema import TABLE_RD25
from .filters import (ACTIVE, FOURTH_EMI, FULLY_PAID, NOT_CANCELLED, NOT_FREE, SENIOR,
                      resolve_scope)
from .query import count_rows, fmt_int, fmt_pct, pct, provenance, require, target_lookup
from .result import ToolResult


def senior_retention(center: str | None = None, region: str | None = None) -> ToolResult:
    """Seniors retained from AY2025. Daily_tracker G3, a two-part sum.

    Part 1 counts 'Total Paid' seniors, part 2 counts '4th EMI Paid' seniors, under
    otherwise identical filters. Both parts require more than one enrolled year, an
    active status, a non-free admission and a non-cancelled form.
    """
    metric = "senior_retention"
    blocked = require(metric, TABLE_RD25)
    if blocked:
        return blocked
    scope = resolve_scope(center, region)
    if not scope.ok:
        return ToolResult.needs_clarification(
            metric, scope.clarification or "", scope.candidates)

    shared = [*scope.clauses, SENIOR, NOT_FREE, ACTIVE, NOT_CANCELLED]
    fully = count_rows(TABLE_RD25, [*shared, FULLY_PAID], scope.params)
    fourth = count_rows(TABLE_RD25, [*shared, FOURTH_EMI], scope.params)
    value = fully + fourth

    target = target_lookup("retention_target", scope)
    achieved = pct(value, target)   # H3 = IFERROR(G3/F3,"")

    summary = f"{fmt_int(value)} senior students retained at {scope.describe()}"
    if target:
        summary += f" against a target of {fmt_int(target)} ({fmt_pct(achieved)} achieved)"
    return ToolResult(
        metric=metric,
        summary=summary + ".",
        values={"value": value, "fully_paid": fully, "fourth_emi": fourth,
                "target": target, "achieved_pct": achieved, "scope": scope.describe()},
        columns=["Payment stage", "Students"],
        rows=[["Total Paid", fully], ["4th EMI Paid", fourth]],
        provenance=provenance(
            metric, [TABLE_RD25], [*shared, FULLY_PAID], scope, row_count=value,
            notes=[f"two-part formula: {fully} fully paid + {fourth} at 4th EMI"]),
    )


def senior_retention_pct(center: str | None = None, region: str | None = None) -> ToolResult:
    """Retention achievement against target. Daily_tracker H3."""
    base = senior_retention(center=center, region=region)
    if not base.ok:
        return base
    if base.values.get("target") is None:
        return ToolResult.unavailable(
            "senior_retention_pct",
            "retention targets are not loaded, so achievement cannot be computed")
    achieved = base.values.get("achieved_pct")
    return ToolResult(
        metric="senior_retention_pct",
        summary=(f"Senior retention at {base.values.get('scope')} is "
                 f"{fmt_pct(achieved)} of target."),
        values={"value": achieved, "retained": base.values.get("value"),
                "target": base.values.get("target"), "scope": base.values.get("scope")},
        provenance=base.provenance,
    )
