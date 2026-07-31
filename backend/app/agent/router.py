"""Skill selection.

The router picks exactly one skill and never answers the question — keeping selection
and answering apart means a routing mistake produces the wrong specialist rather than a
confidently wrong number.

An LLM makes the choice. A deterministic keyword pass scores the triggers declared in
each SKILL.md and is used when the model is unavailable, returns nonsense, or names a
skill that does not exist. That fallback is what the tests exercise, so routing behaviour
is verifiable without a model.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..core.config import settings
from . import llm, prompts
from .skills import FALLBACK_SKILL_ID, Skill, get_skill, list_skills

log = logging.getLogger(__name__)

_NON_WORD = re.compile(r"[^a-z0-9]+")

# One shared word with an intent sentence means nothing — "centers" appears in almost
# every skill's intents. Two or more is a signal.
_MIN_INTENT_OVERLAP = 2

# Words too common to signal intent when matching against a skill's intent sentences.
_STOPWORDS = frozenset("""
a an and are as at be by can do does for from get give has have how i in is it its me
many much of on or our show tell that the their there they this to us was we what when
which who why will with you your
""".split())


@dataclass
class Route:
    skill: Skill
    reason: str
    method: str          # "llm" | "keyword"

    @property
    def skill_id(self) -> str:
        return self.skill.skill_id


def _normalize(text: str) -> str:
    return _NON_WORD.sub(" ", (text or "").lower()).strip()


def _score(skill: Skill, normalized: str) -> tuple[int, int, list[str]]:
    """Trigger score, intent score and which triggers matched.

    Triggers are matched as whole phrases, so "hi" cannot match inside "which", and
    score by length, so a specific phrase like "auto pay" outranks a generic word.
    """
    padded = f" {normalized} "
    matched: list[str] = []
    trigger_score = 0
    for trigger in skill.triggers:
        norm = _normalize(trigger)
        if norm and f" {norm} " in padded:
            matched.append(trigger)
            trigger_score += len(norm)

    words = {w for w in normalized.split() if w not in _STOPWORDS and len(w) > 2}
    intent_score = 0
    for intent in skill.intents:
        overlap = words & {w for w in _normalize(intent).split()
                           if w not in _STOPWORDS and len(w) > 2}
        if len(overlap) >= _MIN_INTENT_OVERLAP:
            intent_score = max(intent_score, len(overlap))
    return trigger_score, intent_score, matched


def keyword_route(message: str) -> Route:
    """Deterministic routing from the triggers declared in each SKILL.md."""
    normalized = _normalize(message)
    ranked: list[tuple[int, int, Skill, list[str]]] = []
    for skill in list_skills():
        trigger_score, intent_score, matched = _score(skill, normalized)
        if trigger_score or intent_score:
            ranked.append((trigger_score, intent_score, skill, matched))

    if not ranked:
        return Route(skill=get_skill(FALLBACK_SKILL_ID),
                     reason="no domain keywords matched", method="keyword")

    # Alphabetical skill_id breaks ties so routing is identical on every run.
    ranked.sort(key=lambda r: (-r[0], -r[1], r[2].skill_id))
    trigger_score, intent_score, skill, matched = ranked[0]
    if matched:
        reason = f"matched {', '.join(matched[:4])}"
    else:
        reason = f"closest intent match ({intent_score} shared terms)"
    return Route(skill=skill, reason=reason, method="keyword")


async def route(message: str, history: list[dict] | None = None) -> Route:
    """Pick one skill, preferring the model and falling back to keywords."""
    fallback = keyword_route(message)
    if not settings.llm_api_key:
        return fallback

    try:
        choice = await _llm_choice(message, history)
    except Exception as e:  # noqa: BLE001 - routing must never fail the turn
        log.warning("Router LLM unavailable (%s); using keyword routing", e)
        return fallback

    if choice is None:
        return fallback
    skill_id, reason = choice
    skill = get_skill(skill_id)
    if skill.skill_id != skill_id:
        log.info("Router chose unknown skill %r; using keyword routing", skill_id)
        return fallback
    return Route(skill=skill, reason=reason or "selected by router", method="llm")


async def _llm_choice(message: str,
                      history: list[dict] | None) -> tuple[str, str] | None:
    messages: list[dict] = [{"role": "system", "content": prompts.router_prompt()}]
    for turn in (history or [])[-4:]:
        messages.append({"role": turn["role"], "content": turn["content"][:500]})
    messages.append({"role": "user", "content": message})

    choice = await llm.complete(messages, json_mode=True, purpose="routing")
    data = _parse_json(choice.content or "")
    if not isinstance(data, dict):
        return None
    skill_id = data.get("skill_id") or data.get("skill")
    if not isinstance(skill_id, str):
        return None
    reason = data.get("reason")
    return skill_id.strip(), reason.strip() if isinstance(reason, str) else ""


def _parse_json(text: str) -> object:
    """Providers that ignore response_format wrap the JSON in prose or fences."""
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group())
        except ValueError:
            return None
