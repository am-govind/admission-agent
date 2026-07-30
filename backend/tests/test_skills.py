"""Skill definitions are data, so they are validated like data.

A typo in a SKILL.md tool name would otherwise surface as a skill that silently offers
the model fewer tools than intended.
"""
from __future__ import annotations

import pytest

from app.agent import skills
from app.agent.skills.loader import SkillError, load_skill, parse_frontmatter
from app.agent.tools import REGISTRY

EXPECTED = {"admissions", "finance", "revenue", "retention", "cancellations",
            "data-explorer", "knowledge"}


def test_expected_skills_load():
    assert {s.skill_id for s in skills.list_skills()} == EXPECTED


def test_every_declared_tool_exists():
    for skill in skills.list_skills():
        for name in skill.tool_names:
            assert name in REGISTRY, f"{skill.skill_id} declares unknown tool {name!r}"


def test_metadata_is_populated():
    for skill in skills.list_skills():
        assert skill.name and skill.description
        assert skill.instructions.strip(), f"{skill.skill_id} has an empty body"
        if skill.skill_id != skills.FALLBACK_SKILL_ID:
            assert skill.required_tool_names, f"{skill.skill_id} declares no required tools"
            assert skill.triggers, f"{skill.skill_id} declares no triggers"


def test_knowledge_skill_is_the_fallback():
    assert skills.get_skill("does-not-exist").skill_id == skills.FALLBACK_SKILL_ID


def test_catalogue_lists_every_skill():
    catalogue = skills.catalogue()
    for skill in skills.list_skills():
        assert skill.skill_id in catalogue


def test_tools_are_covered_by_some_skill():
    """An unreachable tool is dead code; the model can only call a skill's tools."""
    declared = {n for s in skills.list_skills() for n in s.tool_names}
    assert set(REGISTRY) - declared == set()


def test_frontmatter_requires_delimiters():
    with pytest.raises(SkillError):
        parse_frontmatter("no frontmatter here", "test")


def test_unknown_frontmatter_key_is_rejected(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: X\ndescription: y\nsurprise: true\n---\nBody\n")
    with pytest.raises(SkillError):
        load_skill(path)
