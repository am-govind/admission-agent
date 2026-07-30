"""Router tests — the keyword fallback picks the right skill.

These test the deterministic fallback path (no LLM needed), which also guarantees
sensible routing when Ollama is unavailable.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app.agent.router import _keyword_route  # noqa: E402
from app.agent.skills import SKILLS  # noqa: E402


@pytest.mark.parametrize("message,expected", [
    ("What's the ARPU for Nagpur?", "revenue"),
    ("How many students paid their 2nd EMI?", "finance"),
    ("Auto-pay penetration for Pune", "finance"),
    ("Senior retention rate for Chennai", "retention"),
    ("What's the churn rate at Latur?", "cancellations"),
    ("Show me sample rows from the data", "data_explorer"),
    ("Class-wise breakdown for Bengaluru", "admissions"),
    ("How many admissions this month?", "admissions"),
    ("What does ARPU mean?", "revenue"),  # 'arpu' keyword wins; LLM would pick knowledge
    ("Tell me a joke", "knowledge"),
])
def test_keyword_route(message, expected):
    assert _keyword_route(message).skill_id == expected


def test_all_skills_registered():
    for sid in ["admissions", "finance", "revenue", "retention", "cancellations",
                "data_explorer", "knowledge"]:
        assert sid in SKILLS
