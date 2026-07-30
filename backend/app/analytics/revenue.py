"""ARPU and revenue metrics from the Finance sheet, rows 68+."""
from __future__ import annotations

from ..core.database import execute
from ..data import registry
from ..data.schema import TABLE_RD26
from .filters import (ACTIVE, ARPU_CHECKED, CONFIRMED_STRICT, NOT_FREE, NOT_TOKEN,
                      Scope, resolve_scope)
from .query import (avg_column, count_rows, fmt_money, fmt_pct, pct, provenance, require,
                    target_lookup)
from .result import ChartSpec, ToolResult

# Finance D68 population: validated ARPU rows for confirmed, active, paying students.
_ARPU_FILTERS = [NOT_FREE, ACTIVE, ARPU_CHECKED, CONFIRMED_STRICT, NOT_TOKEN]

_CRORE = 10_000_000


def _label(delta: float | None) -> str | None:
    """Finance G68 = IF(E68<0,"Profit",IF(E68>0,"Loss","Threshold"))."""
    if delta is None:
        return None
    if delta < 0:
        return "Profit"
    return "Loss" if delta > 0 else "Threshold"


def arpu(center: str | None = None, region: str | None = None) -> ToolResult:
    """Average revenue per user. Finance D68, with E68, F68, G68 and I68."""
    metric = "arpu"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked
    scope = resolve_scope(center, region)
    if not scope.ok:
        return ToolResult.needs_clarification(
            metric, scope.clarification or "", scope.candidates)

    clauses = [*scope.clauses, *_ARPU_FILTERS]
    value = avg_column(TABLE_RD26, "arpu", clauses, scope.params)
    if value is None:
        return ToolResult.unavailable(
            metric, f"no ARPU-validated students match {scope.describe()}")

    population = count_rows(TABLE_RD26, clauses, scope.params)
    target = target_lookup("arpu_target", scope, aggregate="AVG")
    delta = (target - value) if target is not None else None      # E68 = C68 - D68
    shortfall = pct(delta, target) if target else None            # F68
    # I68 = D68 * H68 / 1e7. H68 is the adjacent student count; the population that
    # entered the average is used here, and named in provenance so it is auditable.
    crores = value * population / _CRORE

    summary = f"ARPU at {scope.describe()} is {fmt_money(value)} across {population:,} students"
    if target is not None:
        summary += (f", against a target of {fmt_money(target)} — a gap of "
                    f"{fmt_money(abs(delta or 0))} ({_label(delta)}, "
                    f"{fmt_pct(abs(shortfall)) if shortfall is not None else 'n/a'})")
    return ToolResult(
        metric=metric,
        summary=summary + f". Estimated revenue {crores:.2f} crore.",
        values={"value": value, "target": target, "delta": delta,
                "shortfall_pct": shortfall, "label": _label(delta),
                "students": population, "revenue_crores": round(crores, 2),
                "scope": scope.describe()},
        provenance=provenance(
            metric, [TABLE_RD26], clauses, scope, row_count=population,
            notes=[f"revenue estimate multiplies ARPU by the {population} students "
                   "in the averaged population"]),
    )


def arpu_by_center(region: str | None = None) -> ToolResult:
    """ARPU for every center, worst first — the follow-up list."""
    metric = "arpu_by_center"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked

    clauses = list(_ARPU_FILTERS)
    params: list[object] = []
    scope = Scope(label="all centers")
    if region:
        scope = resolve_scope(region=region)
        if not scope.ok:
            return ToolResult.needs_clarification(
                metric, scope.clarification or "", scope.candidates)
        clauses = [*scope.clauses, *clauses]
        params = [*scope.params]

    where = " AND ".join(clauses)
    rows = execute(
        f"SELECT center, AVG(arpu) AS arpu, COUNT(*) AS students FROM {TABLE_RD26} "
        f"WHERE {where} GROUP BY center ORDER BY arpu ASC", params)

    table = [[r[0], round(float(r[1]), 2), int(r[2])] for r in rows]
    if not table:
        return ToolResult.unavailable(metric, f"no ARPU-validated students for {scope.describe()}")

    lowest = table[0]
    return ToolResult(
        metric=metric,
        summary=(f"ARPU across {len(table)} centers for {scope.describe()}; lowest is "
                 f"{lowest[0]} at {fmt_money(lowest[1])}."),
        values={"centers": len(table), "lowest_center": lowest[0],
                "lowest_arpu": lowest[1], "scope": scope.describe()},
        columns=["Center", "ARPU", "Students"],
        rows=table,
        chart=ChartSpec(kind="bar", x="Center", y=["ARPU"],
                        title=f"ARPU by center — {scope.describe()}"),
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=len(table)),
    )


def revenue_estimate(center: str | None = None, region: str | None = None) -> ToolResult:
    """Estimated revenue in crores. Finance I68."""
    base = arpu(center=center, region=region)
    if not base.ok:
        return base
    crores = base.values.get("revenue_crores")
    return ToolResult(
        metric="revenue_estimate",
        summary=(f"Estimated revenue for {base.values.get('scope')} is {crores} crore "
                 f"({base.values.get('students'):,} students at "
                 f"{fmt_money(base.values.get('value'))} ARPU)."),
        values={"value": crores, "arpu": base.values.get("value"),
                "students": base.values.get("students"),
                "scope": base.values.get("scope")},
        provenance=base.provenance,
    )


def arpu_gap_leaders(limit: int = 10) -> ToolResult:
    """Centers furthest below their ARPU target. Finance E68 ranked."""
    metric = "arpu_gap_leaders"
    blocked = require(metric, TABLE_RD26)
    if blocked:
        return blocked

    rows: list[list[object]] = []
    for center in registry.all_centers():
        result = arpu(center=center)
        if not result.ok:
            continue
        delta = result.values.get("delta")
        if delta is None:
            continue
        rows.append([center, round(float(result.values["value"]), 2),
                     round(float(result.values["target"]), 2), round(float(delta), 2),
                     result.values.get("label")])

    if not rows:
        return ToolResult.unavailable(
            metric, "ARPU targets are not loaded, so gaps to target cannot be ranked")

    rows.sort(key=lambda r: float(r[3]), reverse=True)
    top = rows[:max(1, min(limit, 53))]
    return ToolResult(
        metric=metric,
        summary=(f"{top[0][0]} has the largest ARPU shortfall at "
                 f"{fmt_money(top[0][3])} below target."),
        values={"worst_center": top[0][0], "worst_gap": top[0][3]},
        columns=["Center", "ARPU", "Target", "Gap", "Status"],
        rows=top,
        chart=ChartSpec(kind="bar", x="Center", y=["Gap"],
                        title="ARPU shortfall by center"),
        provenance=provenance(metric, [TABLE_RD26], _ARPU_FILTERS, None,
                              row_count=len(rows),
                              notes=["positive gap means below target"]),
    )
