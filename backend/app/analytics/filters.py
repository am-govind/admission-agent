"""Shared SQL predicates, declared exactly once.

Every threshold and status test in the workbook lives here, with the cell it came
from. This file is the reason business logic is not written inline in the tool
functions: the workbook deliberately uses BOTH `> 3498` and `>= 3498` depending on
the metric, and that distinction is only auditable if the two live side by side.

Source: Business_Logic_Report_DETAILED.pdf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..data import registry
from ..data.schema import CLASSWISE_TOKENS

# ---------- the 3,498 threshold (Rule 1) ----------
# Below this a payment is a token booking, not an admission. Which comparison a
# metric uses is not interchangeable; it is copied from that metric's own formula.
CONFIRMED_AMOUNT = 3498
# Registration / monthly / DOD / ARPU / loan eligibility: L:L > 3498
CONFIRMED_STRICT = "fees_paid > 3498"
# 1st EMI, auto-pay, class-wise breakdown: L:L >= 3498
CONFIRMED_INCL = "fees_paid >= 3498"

# ---------- status filters (Rules 2 and 3) ----------
NOT_FREE = "free_admission = FALSE"          # Q:Q = FALSE
ACTIVE = "status = 'Active'"                 # P:P = 'Active'

# ---------- payment milestone (Rule 4) ----------
# N:N <> "*token*". A substring test, not equality: three observed values contain
# "Token" ("Token Only", "Less than Token", "Paid btw Token & 1st EMI") and the
# workbook's wildcard excludes all three.
NOT_TOKEN = "COALESCE(newpayment_checks, '') NOT ILIKE '%token%'"
IS_TOKEN = "COALESCE(newpayment_checks, '') ILIKE '%token%'"
NOT_FIRST_EMI = "COALESCE(newpayment_checks, '') <> '1st EMI Paid'"   # Finance M2
FULLY_PAID = "newpayment_checks = 'Total Paid'"                        # Daily_tracker G3 part 1
FOURTH_EMI = "newpayment_checks = '4th EMI Paid'"                      # Daily_tracker G3 part 2

# ---------- form status ----------
CANCELLED = "form_status = 'Admission Cancelled'"                       # Cancelled D2
NOT_CANCELLED = "COALESCE(form_status, '') <> 'Admission Cancelled'"    # S:S <> 'Admission Cancelled'

# ---------- eligibility (Finance H2 / J2) ----------
LOAN_ELIGIBLE = "eligibility_status = 'Eligible'"
LOAN_NOT_ELIGIBLE = "eligibility_status ILIKE '%not eligible%'"

# ---------- auto-pay (Finance F2) ----------
# R:R <> "" AND R:R <> "*Disbural*" AND R:R <> "*Cancel*".
# "Disbural" is the workbook's own spelling. The live data spells the equivalent
# state "READY_FOR_DISBURSAL", which that wildcard does not match, so those rows
# count as auto-pay here exactly as they do in the sheet. Reproducing the sheet is
# the goal; changing the pattern would silently change the published number.
AUTOPAY = ("COALESCE(ep_status, '') <> '' "
           "AND ep_status NOT ILIKE '%disbural%' "
           "AND ep_status NOT ILIKE '%cancel%'")

# ---------- ARPU (Finance D68) ----------
# U:U = "yes". Stored as "Yes"/"No", so the comparison is case-insensitive.
ARPU_CHECKED = "lower(COALESCE(arpu_check, '')) = 'yes'"

# ---------- seniority (Daily_tracker G3) ----------
SENIOR = "enrolled_years > 1"                # G:G > 1

# ---------- Finance Dump specific (Finance L2) ----------
# Different column positions to the RD dumps, same normalised names.
REGULAR_SCHEME_FALSE = "vp_ps_regular_schemes = FALSE"   # T:T = FALSE
HAS_BATCH = "COALESCE(batch, '') <> 'No Batch'"          # D:D <> 'No Batch'

# The confirmed-registration base used as the denominator across Finance,
# Daily_tracker and Admission Cancelled.
CONFIRMED_BASE = [CONFIRMED_STRICT, NOT_FREE, ACTIVE]


@dataclass
class Scope:
    """A resolved center/region/city filter, or a reason it could not be resolved."""

    center: str | None = None
    region: str | None = None
    label: str = "all centers"
    clauses: list[str] = field(default_factory=list)
    params: list[Any] = field(default_factory=list)
    clarification: str | None = None
    candidates: list[str] = field(default_factory=list)
    # City groups and exclusions resolve to an explicit center list rather than one name.
    city: str | None = None
    centers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.clarification is None

    def describe(self) -> str:
        return self.label


def resolve_scope(center: str | None = None, region: str | None = None,
                  exclude: str | None = None) -> Scope:
    """Turn free-text center/region/city input into SQL predicates.

    The workbook matches center AND region together (F:F and A:A). Center-to-region
    is one-to-one in the data, so pinning both is faithful and guards against a
    center name that ever appears under two regions.

    `exclude` subtracts a center, city or region from whatever the rest of the scope
    selected, which is what "Mumbai versus the rest of Maharashtra" needs. Comparing a
    part against the whole double-counts the part, so the exclusion has to happen in SQL
    rather than by subtracting two answers afterwards.
    """
    term = center or region
    scope = _base_scope(term)
    if not scope.ok or not exclude or not str(exclude).strip():
        return scope
    return _with_exclusion(scope, str(exclude))


def _base_scope(term: str | None) -> Scope:
    if not term or not str(term).strip():
        return Scope(label="all centers")

    resolution = registry.resolve(str(term))

    if resolution.kind == "center":
        clauses = ["center = ?"]
        params: list[Any] = [resolution.value]
        if resolution.region:
            clauses.append("region = ?")
            params.append(resolution.region)
        return Scope(center=resolution.value, region=resolution.region,
                     label=str(resolution.value), clauses=clauses, params=params,
                     centers=[str(resolution.value)])

    if resolution.kind == "city":
        members = resolution.members
        placeholders = ", ".join("?" for _ in members)
        clauses = [f"center IN ({placeholders})"]
        params = list(members)
        if resolution.region:
            clauses.append("region = ?")
            params.append(resolution.region)
        return Scope(city=resolution.value, region=resolution.region,
                     label=f"{resolution.value} ({len(members)} centers)",
                     clauses=clauses, params=params, centers=members)

    if resolution.kind == "region":
        members = registry.centers_in_region(str(resolution.value))
        return Scope(region=resolution.value, label=f"{resolution.value} region",
                     clauses=["region = ?"], params=[resolution.value], centers=members)

    if resolution.kind == "ambiguous":
        options = ", ".join(resolution.candidates)
        return Scope(
            clarification=(f"{term!r} matches centers in more than one city. Which did "
                           f"you mean: {options}?"),
            candidates=resolution.candidates)

    known = ", ".join(resolution.candidates[:8]) if resolution.candidates else "none loaded"
    return Scope(
        clarification=(f"I do not recognise {term!r} as a center, city or region. "
                       f"Known centers include: {known}."),
        candidates=resolution.candidates)


def _with_exclusion(scope: Scope, exclude: str) -> Scope:
    """Subtract a center, city or region from an already-resolved scope."""
    removed = _base_scope(exclude)
    if not removed.ok:
        return Scope(clarification=removed.clarification, candidates=removed.candidates)

    clauses = list(scope.clauses)
    params = list(scope.params)
    # Excluding a whole region is one predicate; only a center or city needs the list.
    if removed.region and not removed.center and not removed.city:
        clauses.append("region <> ?")
        params.append(removed.region)
    else:
        placeholders = ", ".join("?" for _ in removed.centers)
        clauses.append(f"center NOT IN ({placeholders})")
        params.extend(removed.centers)

    # Only meaningful when the base scope enumerated its centers; a bare region does.
    remaining = [c for c in scope.centers if c not in set(removed.centers)]
    label = f"{scope.label} excluding {_plain_name(removed)}"
    if remaining:
        label += f" ({len(remaining)} centers)"
    return Scope(center=scope.center, region=scope.region, city=scope.city,
                 label=label, clauses=clauses, params=params, centers=remaining)


def _plain_name(scope: Scope) -> str:
    """The undecorated name of a scope, for composing into another scope's label."""
    if scope.city:
        return scope.city
    if scope.center:
        return scope.center
    return f"{scope.region} region" if scope.region else "all centers"


@dataclass
class ClassFilter:
    """A resolved class/course restriction, or a reason it could not be resolved."""

    # The (label, wildcard) pairs selected, in workbook order. Empty means "all nine",
    # which the class-wise breakdown needs in order to emit a column per class.
    tokens: list[tuple[str, str]] = field(default_factory=list)
    clauses: list[str] = field(default_factory=list)
    params: list[Any] = field(default_factory=list)
    clarification: str | None = None
    requested: bool = False

    @property
    def ok(self) -> bool:
        return self.clarification is None

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self.tokens]

    @property
    def label(self) -> str:
        return ", ".join(self.labels)


def resolve_classes(classes: list[str] | None) -> ClassFilter:
    """Turn requested class names into one OR-ed ILIKE predicate.

    Matching is by the same wildcard tokens the workbook's class columns use, so a
    filtered count and the class-wise breakdown agree by construction rather than by
    two separate lists of spellings staying in step.
    """
    if not classes:
        return ClassFilter(tokens=list(CLASSWISE_TOKENS))

    wanted = {c.strip().lower() for c in classes if c and c.strip()}
    tokens = [t for t in CLASSWISE_TOKENS if t[0].lower() in wanted]
    if not tokens:
        valid = ", ".join(label for label, _ in CLASSWISE_TOKENS)
        return ClassFilter(clarification=(
            f"None of {classes} matched a tracked class. Valid classes: {valid}."))

    ors = " OR ".join("class_course ILIKE ?" for _ in tokens)
    return ClassFilter(
        tokens=tokens,
        clauses=[f"({ors})"],
        params=[f"%{token}%" for _, token in tokens],
        requested=True)


def describe_filters(clauses: list[str]) -> list[str]:
    """Human-readable filter list for provenance."""
    friendly = {
        CONFIRMED_STRICT: "fees paid > 3,498",
        CONFIRMED_INCL: "fees paid >= 3,498",
        NOT_FREE: "excluding free admissions",
        ACTIVE: "active students only",
        NOT_TOKEN: "excluding token-only payments",
        IS_TOKEN: "token-only payments",
        NOT_FIRST_EMI: "beyond 1st EMI",
        FULLY_PAID: "payment status 'Total Paid'",
        FOURTH_EMI: "payment status '4th EMI Paid'",
        CANCELLED: "form status 'Admission Cancelled'",
        NOT_CANCELLED: "excluding cancelled admissions",
        LOAN_ELIGIBLE: "loan eligibility 'Eligible'",
        LOAN_NOT_ELIGIBLE: "loan eligibility 'Not Eligible'",
        AUTOPAY: "active auto-pay mandate",
        ARPU_CHECKED: "ARPU-validated rows only",
        SENIOR: "enrolled more than 1 year",
        REGULAR_SCHEME_FALSE: "excluding regular schemes",
        HAS_BATCH: "batch assigned",
    }
    return [friendly.get(c, c) for c in clauses]
