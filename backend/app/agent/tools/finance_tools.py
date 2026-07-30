"""Finance, revenue, retention and cancellation tools. Wrappers only."""
from __future__ import annotations

from ...analytics import cancellations, finance, retention, revenue
from ...analytics.result import ToolResult
from .registry import (LimitParams, RegionLimitParams, RegionParams, ScopeParams, tool)


# ---------- collections ----------

@tool("get_first_emi",
      "How many registered students have made a real payment beyond a booking token, "
      "with the conversion rate. The registered-to-paying conversion metric.",
      ScopeParams)
def get_first_emi(center: str | None = None, region: str | None = None) -> ToolResult:
    return finance.first_emi(center=center, region=region)


@tool("get_autopay",
      "How many students have an active auto-pay / e-mandate set up, and the "
      "penetration rate. Use for auto-pay, ENACH, mandate or 'predictable cash flow' "
      "questions.",
      ScopeParams)
def get_autopay(center: str | None = None, region: str | None = None) -> ToolResult:
    return finance.autopay(center=center, region=region)


@tool("get_loan_eligibility",
      "How many students qualify for an education loan or financial aid, and how many "
      "do not, with both rates.",
      ScopeParams)
def get_loan_eligibility(center: str | None = None,
                         region: str | None = None) -> ToolResult:
    return finance.loan_eligibility(center=center, region=region)


@tool("get_second_emi",
      "2nd-EMI collection: the eligible base, how many have paid, the collection rate "
      "and how many still owe. The follow-up list size for the collections team.",
      ScopeParams)
def get_second_emi(center: str | None = None, region: str | None = None) -> ToolResult:
    return finance.second_emi(center=center, region=region)


@tool("get_finance_summary",
      "Every finance metric for one scope in a single call: registrations, 1st EMI, "
      "auto-pay, loan eligibility and 2nd-EMI collection. Prefer this over several "
      "separate calls when the question is broad.",
      ScopeParams)
def get_finance_summary(center: str | None = None,
                        region: str | None = None) -> ToolResult:
    return finance.finance_summary(center=center, region=region)


# ---------- retention ----------

@tool("get_senior_retention",
      "How many senior students from last academic year have been retained, split by "
      "the payment stage they reached, with target and achievement.",
      ScopeParams)
def get_senior_retention(center: str | None = None,
                         region: str | None = None) -> ToolResult:
    return retention.senior_retention(center=center, region=region)


@tool("get_senior_retention_pct",
      "Senior retention as a percentage of the retention target.",
      ScopeParams)
def get_senior_retention_pct(center: str | None = None,
                             region: str | None = None) -> ToolResult:
    return retention.senior_retention_pct(center=center, region=region)


# ---------- revenue ----------

@tool("get_arpu",
      "Average revenue per user for a scope, with the ARPU target, the gap, the "
      "shortfall percentage, a Profit/Loss/Threshold label and an estimated revenue "
      "figure in crores.",
      ScopeParams)
def get_arpu(center: str | None = None, region: str | None = None) -> ToolResult:
    return revenue.arpu(center=center, region=region)


@tool("get_arpu_by_center",
      "ARPU for every center, lowest first, with the student count behind each average. "
      "Use to compare centers on per-student revenue.",
      RegionParams)
def get_arpu_by_center(region: str | None = None) -> ToolResult:
    return revenue.arpu_by_center(region=region)


@tool("get_revenue_estimate",
      "Estimated total revenue in crores for a scope, derived from ARPU and the "
      "student count behind it.",
      ScopeParams)
def get_revenue_estimate(center: str | None = None,
                         region: str | None = None) -> ToolResult:
    return revenue.revenue_estimate(center=center, region=region)


@tool("get_arpu_gap_leaders",
      "Centers ranked by how far their ARPU is below target, worst first. Use for "
      "'which centers are underperforming on revenue' questions.",
      LimitParams)
def get_arpu_gap_leaders(limit: int = 10) -> ToolResult:
    return revenue.arpu_gap_leaders(limit=limit)


# ---------- cancellations ----------

@tool("get_cancellations",
      "Cancelled admissions and the churn rate for a scope.",
      ScopeParams)
def get_cancellations(center: str | None = None, region: str | None = None) -> ToolResult:
    return cancellations.cancellations(center=center, region=region)


@tool("get_cancellations_by_center",
      "Cancellations and churn rate per center, highest churn first. Use to find which "
      "centers have a cancellation problem.",
      RegionLimitParams)
def get_cancellations_by_center(region: str | None = None, limit: int = 15) -> ToolResult:
    return cancellations.cancellations_by_center(region=region, limit=limit)
