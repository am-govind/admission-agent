"""Per-conversation memory.

Slot-based rather than a growing transcript: the things a follow-up needs are the
center, region and metric currently under discussion, and those are a handful of short
values. Storing them explicitly means "and for Pune?" works without re-sending the whole
history, and — more importantly — that what was inherited is knowable and can be shown
in provenance.

Slots live in SQLite, so they survive both a data refresh and a restart.
"""
from __future__ import annotations

import logging

from ..core import appdb
from ..core.config import settings
from ..data import conversation
from . import llm

log = logging.getLogger(__name__)

SLOT_CENTER = "center"
SLOT_REGION = "region"
SLOT_METRIC = "metric"
SLOT_SKILL = "skill"
SLOT_SUMMARY = "summary"

SLOT_KEYS = (SLOT_CENTER, SLOT_REGION, SLOT_METRIC, SLOT_SKILL, SLOT_SUMMARY)

# Scope slots are the ones a tool call can inherit.
SCOPE_SLOTS = (SLOT_CENTER, SLOT_REGION)

# Phrases that mean "ignore the center we were just discussing".
_GLOBAL_PHRASES = (
    "all centers", "all center", "every center", "all regions", "every region",
    "across all", "company wide", "company-wide", "organisation", "organization",
    "overall", "in total", "grand total", "everywhere", "whole business", "all india",
)


def load(conversation_id: str) -> dict[str, str]:
    rows = appdb.query(
        "SELECT key, value FROM conversation_memory WHERE conversation_id = ?",
        [conversation_id])
    return {k: v for k, v in rows if v}


def save(conversation_id: str, slots: dict[str, str | None]) -> None:
    """Write slots. A None or empty value clears that slot."""
    for key, value in slots.items():
        if key not in SLOT_KEYS:
            continue
        if value is None or not str(value).strip():
            appdb.execute(
                "DELETE FROM conversation_memory WHERE conversation_id = ? AND key = ?",
                [conversation_id, key])
            continue
        appdb.execute(
            "INSERT INTO conversation_memory (conversation_id, key, value, updated_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(conversation_id, key) DO UPDATE SET "
            "value = excluded.value, updated_at = excluded.updated_at",
            [conversation_id, key, str(value).strip()])


def clear(conversation_id: str) -> None:
    appdb.execute("DELETE FROM conversation_memory WHERE conversation_id = ?",
                  [conversation_id])


def wants_global_scope(message: str) -> bool:
    """True when the user has explicitly asked to widen back out to everything."""
    lowered = (message or "").lower()
    return any(phrase in lowered for phrase in _GLOBAL_PHRASES)


def context_text(slots: dict[str, str]) -> str | None:
    """The '[Current context]' block injected into the system prompt."""
    lines: list[str] = []
    if slots.get(SLOT_CENTER):
        lines.append(f"- Center under discussion: {slots[SLOT_CENTER]}")
    if slots.get(SLOT_REGION) and not slots.get(SLOT_CENTER):
        lines.append(f"- Region under discussion: {slots[SLOT_REGION]}")
    if slots.get(SLOT_METRIC):
        lines.append(f"- Last metric reported: {slots[SLOT_METRIC]}")
    if lines:
        lines.append("If the user does not name a center or region, these still apply. "
                     "If they ask about everything, pass no center or region.")
    if slots.get(SLOT_SUMMARY):
        lines.append(f"\nEarlier in this conversation: {slots[SLOT_SUMMARY]}")
    return "\n".join(lines) if lines else None


def inherit_scope(args: dict, slots: dict[str, str], message: str,
                  accepts: tuple[str, ...]) -> tuple[dict, list[str]]:
    """Fill an omitted center/region from memory. Returns (args, notes).

    Every inheritance is reported in `notes`, which the caller attaches to provenance —
    a number silently scoped to a center the user mentioned three turns ago is exactly
    the kind of thing that erodes trust in the whole system.
    """
    if wants_global_scope(message):
        return args, []
    if any(args.get(key) for key in SCOPE_SLOTS):
        return args, []

    notes: list[str] = []
    updated = dict(args)
    for key in SCOPE_SLOTS:
        if key in accepts and slots.get(key):
            updated[key] = slots[key]
            notes.append(f"{key} '{slots[key]}' carried over from earlier in the "
                         "conversation")
            break
    return updated, notes


def record_result(conversation_id: str, metric: str, values: dict) -> None:
    """Remember the scope a successful tool call actually resolved to."""
    updates: dict[str, str | None] = {SLOT_METRIC: metric}
    scope = values.get("scope")
    if isinstance(scope, str) and scope and scope != "all centers":
        if scope.endswith(" region"):
            updates[SLOT_REGION] = scope[: -len(" region")]
            updates[SLOT_CENTER] = None
        else:
            updates[SLOT_CENTER] = scope
    elif scope == "all centers":
        updates[SLOT_CENTER] = None
        updates[SLOT_REGION] = None
    save(conversation_id, updates)


def history_for_prompt(conversation_id: str) -> list[dict]:
    """The verbatim window: recent turns sent to the model as-is."""
    return conversation.get_history(conversation_id,
                                    limit=max(2, settings.memory_verbatim_turns * 2))


async def update_summary(conversation_id: str) -> None:
    """Refresh the rolling summary once the conversation outgrows the window.

    Best-effort: without a working model there is simply no summary, which is better
    than a fabricated one.
    """
    window = max(2, settings.memory_verbatim_turns * 2)
    total = conversation.message_count(conversation_id)
    if total <= window or not settings.llm_api_key:
        return
    # Refresh once per window rather than on every turn.
    if total % window not in (0, 1):
        return

    older = appdb.query(
        "SELECT role, content FROM messages WHERE conversation_id = ? "
        "ORDER BY turn_id ASC, rowid ASC LIMIT ?", [conversation_id, total - window])
    if not older:
        return

    transcript = "\n".join(f"{role}: {content[:400]}" for role, content in older)
    try:
        choice = await llm.complete(
            [
                {"role": "system", "content":
                    "Summarise this analytics conversation in at most three sentences. "
                    "Keep the centers, regions and metrics discussed and any stated "
                    "preference. Do not restate figures — they may now be out of date."},
                {"role": "user", "content": transcript},
            ],
            purpose="conversation summary")
        summary = (choice.content or "").strip()
    except Exception as e:  # noqa: BLE001 - a missing summary must not fail the turn
        log.warning("Could not update conversation summary: %s", e)
        return

    if summary:
        save(conversation_id, {SLOT_SUMMARY: summary[:1500]})
