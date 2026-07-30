"""Prompt construction.

Three pieces compose the system prompt for a turn: rules that apply to every skill,
the selected skill's own markdown instructions, and a live description of the data
(tables, columns, centers, freshness) generated from the schema so it cannot drift out
of date the way a hand-maintained data dictionary does.
"""
from __future__ import annotations

from ..data import availability, registry
from ..data.reference_date import reference_date
from ..data.schema import (ANALYTICS_TABLES, PII_COLUMNS, TABLE_COLUMN_TYPES,
                           TABLE_LABELS)
from .skills import Skill, catalogue

# Rules that hold no matter which skill is selected.
SHARED_RULES = """\
You are an analytics assistant for a network of coaching centers, answering questions
about admissions and finance for regional and center managers.

Non-negotiable rules:
1. Every figure you state must come from a tool result in this conversation. You do not
   calculate, estimate, extrapolate or recall numbers yourself. If you have no tool
   result for something, say you do not have it.
2. If a tool reports a figure unavailable, tell the user it is unavailable and give the
   reason it returned. Do not substitute a different metric or a partial proxy.
3. If a tool asks for clarification, put that question to the user and stop. Do not
   pick one of the options on their behalf.
4. Never reveal or repeat student names or registration numbers, even if they appear in
   data you receive. Report aggregates only.
5. Tables and charts you receive from tools are already displayed to the user. Do not
   reproduce them as markdown. Summarise what they show in two or three sentences and
   point at the notable rows.
6. Lead with the number the user asked for. Add context — target, rate, comparison —
   after it, not before.
7. All periods are measured from the reference date (the latest admission in the data),
   not from today. Name the month or date you are reporting so it is unambiguous.
8. Money is in Indian rupees. Write large amounts as ₹1,23,456 or in crores.
"""


def data_context() -> str:
    """Live description of what is loaded, for the answering prompt."""
    lines: list[str] = []
    statuses = availability.statuses()

    lines.append("Tables:")
    for table in ANALYTICS_TABLES:
        status = statuses[table]
        label = TABLE_LABELS.get(table, table)
        if not status.usable:
            lines.append(f"- {table} ({label}): NOT AVAILABLE — {status.reason}")
            continue
        columns = [c for c in TABLE_COLUMN_TYPES.get(table, {}) if c not in PII_COLUMNS]
        lines.append(f"- {table} ({label}): {status.rows:,} rows; "
                     f"columns {', '.join(columns)}")

    regions = registry.all_regions()
    centers = registry.all_centers()
    if regions:
        lines.append(f"\nRegions: {', '.join(regions)}")
    if centers:
        lines.append(f"Centers ({len(centers)}): {', '.join(centers)}")
    lines.append(f"\nReference date: {reference_date().isoformat()}")

    note = availability.staleness_note()
    if note:
        lines.append(f"Freshness warning: {note}")
    return "\n".join(lines)


def system_prompt(skill: Skill, memory_context: str | None = None) -> str:
    """Full system prompt for the answering loop."""
    sections = [SHARED_RULES, f"# Skill: {skill.name}\n\n{skill.instructions}",
                f"# Data available\n\n{data_context()}"]
    if memory_context:
        sections.append(f"# Current context\n\n{memory_context}")
    return "\n\n".join(sections)


def router_prompt() -> str:
    """System prompt for skill selection. The router never answers the question."""
    details: list[str] = []
    for line in catalogue().splitlines():
        details.append(line)
    from .skills import list_skills
    intents = []
    for skill in list_skills():
        if skill.intents:
            joined = "; ".join(skill.intents)
            intents.append(f"- {skill.skill_id}: {joined}")

    return (
        "You route a user's message to exactly one skill. You do not answer the "
        "question and you do not compute anything.\n\n"
        "Skills:\n" + "\n".join(details) + "\n\n"
        "What each skill handles:\n" + "\n".join(intents) + "\n\n"
        "Rules:\n"
        "- Choose the single best skill id.\n"
        "- A request for a number goes to the metric skill that owns it, never to "
        "knowledge.\n"
        "- A request to define or explain a term, with no number wanted, goes to "
        "knowledge.\n"
        "- Use data-explorer only when no metric skill covers the question.\n"
        "- If the message is a follow-up, route on what is being asked now, using the "
        "earlier turns only to resolve pronouns and omitted scope.\n\n"
        'Reply with JSON only: {"skill_id": "<id>", "reason": "<short reason>"}'
    )
