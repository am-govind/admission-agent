"""Admissions tools. Wrappers only — the logic lives in analytics/admissions.py."""
from __future__ import annotations

from ...analytics import admissions
from ...analytics.result import ToolResult
from .registry import ScopeClassesParams, ScopeDaysParams, ScopeMonthsParams, ScopeParams, tool


@tool("get_fresh_registrations",
      "Total confirmed fresh registrations for a center, a region or the whole "
      "organisation, with target and achievement percentage. This is the headline "
      "'how many admissions do we have' number.",
      ScopeParams)
def get_fresh_registrations(center: str | None = None,
                            region: str | None = None) -> ToolResult:
    return admissions.fresh_registrations(center=center, region=region)


@tool("get_monthly_admissions",
      "Admissions in the current data month, with the monthly target, achievement "
      "percentage and how many more are needed. Use for 'this month' questions.",
      ScopeParams)
def get_monthly_admissions(center: str | None = None,
                           region: str | None = None) -> ToolResult:
    return admissions.monthly_admissions(center=center, region=region)


@tool("get_dod_admissions",
      "Day-on-day admission counts for the most recent days, as a dated series. Use "
      "for 'yesterday', 'daily trend' or 'last N days' questions.",
      ScopeDaysParams)
def get_dod_admissions(center: str | None = None, region: str | None = None,
                       days: int = 20) -> ToolResult:
    return admissions.dod_admissions(center=center, region=region, days=days)


@tool("get_monthly_trend",
      "Month-by-month admission counts, oldest first. Use for 'trend over months', "
      "'month on month' or 'how has it changed' questions.",
      ScopeMonthsParams)
def get_monthly_trend(center: str | None = None, region: str | None = None,
                      months: int = 12) -> ToolResult:
    return admissions.monthly_trend(center=center, region=region, months=months)


@tool("get_classwise_breakdown",
      "Registrations split across the nine tracked classes (8th, 9th, 10th, 11th JEE, "
      "11th NEET, 12th JEE, 12th NEET, Dropper JEE, Dropper NEET). Supports filtering "
      "to specific classes via the 'classes' parameter.",
      ScopeClassesParams)
def get_classwise_breakdown(center: str | None = None,
                            region: str | None = None,
                            classes: list[str] | None = None) -> ToolResult:
    return admissions.classwise_breakdown(center=center, region=region, classes=classes)


@tool("get_pending_admissions",
      "How many more admissions are needed to hit this month's target. Negative means "
      "the target is already exceeded.",
      ScopeParams)
def get_pending_admissions(center: str | None = None,
                           region: str | None = None) -> ToolResult:
    return admissions.pending_admissions(center=center, region=region)


@tool("get_admissions_summary",
      "Every admissions headline for one scope in a single call: registrations, target "
      "and achievement, this month's admissions and gap, and the largest class. Prefer "
      "this over several separate calls when the question is broad.",
      ScopeParams)
def get_admissions_summary(center: str | None = None,
                           region: str | None = None) -> ToolResult:
    return admissions.admissions_summary(center=center, region=region)
