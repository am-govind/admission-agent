"""Router tests, exercising the deterministic fallback.

The fallback is what runs whenever the model is unreachable, so it has to be good on its
own rather than a token backstop.
"""
from __future__ import annotations

import pytest

from app.agent.router import keyword_route
from app.agent.skills import FALLBACK_SKILL_ID, get_skill, list_skills


@pytest.mark.parametrize("message,expected", [
    ("What's the ARPU for Nagpur?", "revenue"),
    ("estimated revenue in crores", "revenue"),
    ("How many students paid their 2nd EMI?", "finance"),
    ("Auto-pay penetration for Pune", "finance"),
    ("loan eligibility approved percentage", "finance"),
    ("Senior retention rate for Chennai", "retention"),
    ("how many AY2025 students continued", "retention"),
    ("What's the cancellation rate at Latur?", "cancellations"),
    ("how many students dropped out", "cancellations"),
    ("Class-wise breakdown for Bengaluru", "admissions"),
    ("How many admissions this month?", "admissions"),
    ("fresh registrations day on day", "admissions"),
    ("run a custom sql query on the dump", "data-explorer"),
    ("what columns does the finance table have", "data-explorer"),
])
def test_keyword_route(message, expected):
    route = keyword_route(message)
    assert route.skill_id == expected, f"{message!r} -> {route.skill_id} ({route.reason})"


@pytest.mark.parametrize("message", [
    "Tell me a joke",
    "hello",
    "what can you do?",
    "who built you",
])
def test_chit_chat_falls_back_to_knowledge(message):
    assert keyword_route(message).skill_id == FALLBACK_SKILL_ID


def test_route_always_resolves_to_a_real_skill():
    for message in ["", "   ", "?????", "asdkjhasd"]:
        route = keyword_route(message)
        assert get_skill(route.skill_id).skill_id == route.skill_id


def test_route_carries_a_reason():
    route = keyword_route("ARPU for Nagpur")
    assert route.reason
    assert route.method == "keyword"


def test_every_skill_is_reachable_by_its_own_triggers():
    """A trigger that cannot select its own skill is a trigger that does nothing."""
    unreachable = []
    for skill in list_skills():
        if skill.skill_id == FALLBACK_SKILL_ID:
            continue
        for trigger in skill.triggers:
            if keyword_route(trigger).skill_id != skill.skill_id:
                unreachable.append(f"{skill.skill_id}: {trigger!r} -> "
                                   f"{keyword_route(trigger).skill_id}")
    assert not unreachable, "; ".join(unreachable)
