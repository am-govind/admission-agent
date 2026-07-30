"""Finance metrics from the Finance sheet.

Each function notes the filters its formula does and does not apply. Those
differences are deliberate: auto-pay (F2) omits the free-admission and active tests
that the registration base (C2) applies, and 1st EMI (D2) uses the inclusive fee
threshold while loan eligibility (H2) uses the strict one. Normalising them would
change published numbers.
"""
from __future__ import annotations

from ..data.schema import TABLE_FINANCE, TABLE_RD26
from . import admissions
from .filters import (ACTIVE, AUTOPAY, CONFIRMED_INCL, CONFIRMED_STRICT, HAS_BATCH,
                      IS_TOKEN, LOAN_ELIGIBLE, LOAN_NOT_ELIGIBLE, NOT_FIRST_EMI,
                      NOT_FREE, NOT_TOKEN, REGULAR_SCHEME_FALSE, Scope, resolve_scope)
from .query import count_rows, fmt_int, fmt_pct, pct, provenance, require
from .result import ChartSpec, ToolResult


def _scoped(metric: str, center: str | None, region: str | None,
            *tables: str) -> tuple[Scope, ToolResult | None]:
    blocked = require(metric, *(tables or (TABLE_RD26,)))
    if blocked:
        return Scope(), blocked
    scope = resolve_scope(center, region)
    if not scope.ok:
        return scope, ToolResult.needs_clarification(
            metric, scope.clarification or "", scope.candidates)
    return scope, None


def first_emi(center: str | None = None, region: str | None = None) -> ToolResult:
    """Students past a booking token. Finance D2, rate E2 = D2/C2."""
    metric = "first_emi"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    clauses = [*scope.clauses, CONFIRMED_INCL, NOT_FREE, ACTIVE, NOT_TOKEN]
    value = count_rows(TABLE_RD26, clauses, scope.params)
    base = admissions.confirmed_count(scope)
    rate = pct(value, base)

    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(value)} of {fmt_int(base)} registered students at "
                 f"{scope.describe()} have made a real payment beyond a token "
                 f"({fmt_pct(rate)})."),
        values={"value": value, "base": base, "rate": rate, "scope": scope.describe()},
        provenance=provenance(metric, [TABLE_RD26], clauses, scope, row_count=value),
    )


def autopay(center: str | None = None, region: str | None = None) -> ToolResult:
    """Active auto-pay mandates. Finance F2, rate G2 = F2/C2."""
    metric = "autopay"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    clauses = [*scope.clauses, CONFIRMED_INCL, AUTOPAY]
    value = count_rows(TABLE_RD26, clauses, scope.params)
    base = admissions.confirmed_count(scope)
    rate = pct(value, base)

    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(value)} students at {scope.describe()} have an active "
                 f"auto-pay mandate ({fmt_pct(rate)} of {fmt_int(base)} registrations)."),
        values={"value": value, "base": base, "rate": rate, "scope": scope.describe()},
        provenance=provenance(
            metric, [TABLE_RD26], clauses, scope, row_count=value,
            notes=["formula F2 does not filter free admissions or active status"]),
    )


def loan_eligibility(center: str | None = None, region: str | None = None) -> ToolResult:
    """Loan-eligible and not-eligible counts. Finance H2/I2 and J2/K2."""
    metric = "loan_eligibility"
    scope, blocked = _scoped(metric, center, region)
    if blocked:
        return blocked

    base_clauses = [*scope.clauses, CONFIRMED_STRICT, NOT_FREE, ACTIVE]
    eligible = count_rows(TABLE_RD26, [*base_clauses, LOAN_ELIGIBLE], scope.params)
    not_eligible = count_rows(TABLE_RD26, [*base_clauses, LOAN_NOT_ELIGIBLE], scope.params)
    base = admissions.confirmed_count(scope)

    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(eligible)} students at {scope.describe()} qualify for a loan "
                 f"({fmt_pct(pct(eligible, base))}); {fmt_int(not_eligible)} do not "
                 f"({fmt_pct(pct(not_eligible, base))})."),
        values={"value": eligible, "eligible": eligible, "not_eligible": not_eligible,
                "base": base, "eligible_pct": pct(eligible, base),
                "not_eligible_pct": pct(not_eligible, base), "scope": scope.describe()},
        columns=["Status", "Students"],
        rows=[["Eligible", eligible], ["Not eligible", not_eligible]],
        provenance=provenance(metric, [TABLE_RD26], [*base_clauses, LOAN_ELIGIBLE],
                              scope, row_count=eligible),
    )


def second_emi(center: str | None = None, region: str | None = None) -> ToolResult:
    """2nd-EMI collection. Finance L2 (base), M2 (paid), N2 (rate), O2 (delta).

    The base is the most involved formula in the workbook: it reads the Finance Dump
    rather than RD26 and adds two counts — students who made a real payment, plus
    token-only students who were nonetheless assigned a batch.
    """
    metric = "second_emi"
    scope, blocked = _scoped(metric, center, region, TABLE_RD26, TABLE_FINANCE)
    if blocked:
        return blocked

    # L2 part 1: real payers.
    part1_clauses = [*scope.clauses, REGULAR_SCHEME_FALSE, ACTIVE, NOT_TOKEN]
    part1 = count_rows(TABLE_FINANCE, part1_clauses, scope.params)
    # L2 part 2: token-only, but progressing because they have a batch.
    part2_clauses = [*scope.clauses, REGULAR_SCHEME_FALSE, ACTIVE, IS_TOKEN, HAS_BATCH]
    part2 = count_rows(TABLE_FINANCE, part2_clauses, scope.params)
    base = part1 + part2

    # M2: paid beyond the 1st EMI, from RD26.
    paid_clauses = [*scope.clauses, NOT_FREE, ACTIVE, NOT_TOKEN, NOT_FIRST_EMI]
    paid = count_rows(TABLE_RD26, paid_clauses, scope.params)

    rate = pct(paid, base)
    delta = base - paid

    return ToolResult(
        metric=metric,
        summary=(f"{fmt_int(paid)} of {fmt_int(base)} students at {scope.describe()} are "
                 f"current on their 2nd EMI ({fmt_pct(rate)}); {fmt_int(delta)} still owe."),
        values={"value": paid, "base": base, "paid": paid, "rate": rate, "delta": delta,
                "base_real_payers": part1, "base_token_with_batch": part2,
                "scope": scope.describe()},
        columns=["Measure", "Students"],
        rows=[["Eligible base", base], ["Paid 2nd EMI", paid], ["Still owing", delta]],
        provenance=provenance(
            metric, [TABLE_FINANCE, TABLE_RD26], part1_clauses, scope, row_count=base,
            notes=["base is Finance Dump; paid count is RD26",
                   f"base = {part1} real payers + {part2} token-with-batch"]),
    )


def finance_summary(center: str | None = None, region: str | None = None) -> ToolResult:
    """Every finance metric for one scope, in a single call."""
    metric = "finance_summary"
    registrations = admissions.fresh_registrations(center=center, region=region)
    if not registrations.ok:
        return registrations

    emi1 = first_emi(center=center, region=region)
    auto = autopay(center=center, region=region)
    loans = loan_eligibility(center=center, region=region)
    emi2 = second_emi(center=center, region=region)

    scope_label = registrations.values.get("scope")
    rows: list[list[object]] = [
        ["Confirmed registrations", registrations.values.get("value"), None],
        ["1st EMI paid", emi1.values.get("value"), _pctstr(emi1.values.get("rate"))],
        ["Auto-pay active", auto.values.get("value"), _pctstr(auto.values.get("rate"))],
        ["Loan eligible", loans.values.get("eligible"),
         _pctstr(loans.values.get("eligible_pct"))],
        ["Loan not eligible", loans.values.get("not_eligible"),
         _pctstr(loans.values.get("not_eligible_pct"))],
    ]
    if emi2.ok:
        rows.append(["2nd EMI paid", emi2.values.get("paid"),
                     _pctstr(emi2.values.get("rate"))])
        rows.append(["2nd EMI still owing", emi2.values.get("delta"), None])
        note = None
    else:
        note = emi2.unavailable_reason

    summary = f"Finance summary for {scope_label}."
    if note:
        summary += f" 2nd-EMI collection is unavailable because {note}."

    return ToolResult(
        metric=metric,
        summary=summary,
        values={"registrations": registrations.values.get("value"),
                "first_emi": emi1.values.get("value"),
                "autopay": auto.values.get("value"),
                "loan_eligible": loans.values.get("eligible"),
                "second_emi_paid": emi2.values.get("paid") if emi2.ok else None,
                "scope": scope_label},
        columns=["Measure", "Students", "Rate"],
        rows=rows,
        chart=ChartSpec(kind="bar", x="Measure", y=["Students"],
                        title=f"Finance funnel — {scope_label}"),
        provenance=registrations.provenance,
    )


def _pctstr(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:.1f}%"
