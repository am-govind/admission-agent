"""Skill registry.

Loaded once at import from definitions/*/SKILL.md, and cross-checked against the tool
registry so a mistyped tool name fails at startup rather than at 3am when someone asks
a question that needed it.
"""
from __future__ import annotations

from pathlib import Path

from ..tools import REGISTRY as TOOL_REGISTRY
from .loader import Skill, SkillError, load_all, load_skill, parse_frontmatter

DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"

# The skill used when nothing else fits; it answers from conversation and definitions.
FALLBACK_SKILL_ID = "knowledge"


def _validate_tools(skills: dict[str, Skill]) -> None:
    problems: list[str] = []
    for skill in skills.values():
        for name in skill.tool_names:
            if name not in TOOL_REGISTRY:
                problems.append(f"{skill.skill_id}: unknown tool {name!r}")
    if problems:
        raise SkillError(
            "SKILL.md files reference tools that are not registered:\n  "
            + "\n  ".join(problems))


SKILLS: dict[str, Skill] = load_all(DEFINITIONS_DIR)
_validate_tools(SKILLS)

if FALLBACK_SKILL_ID not in SKILLS:
    raise SkillError(
        f"a {FALLBACK_SKILL_ID!r} skill is required as the routing fallback; "
        f"found: {', '.join(sorted(SKILLS))}")


def list_skills() -> list[Skill]:
    return [SKILLS[k] for k in sorted(SKILLS)]


def get_skill(skill_id: str | None) -> Skill:
    """Look up a skill, falling back to knowledge for anything unrecognised."""
    if skill_id and skill_id in SKILLS:
        return SKILLS[skill_id]
    return SKILLS[FALLBACK_SKILL_ID]


def get_instructions(skill_id: str) -> str:
    return get_skill(skill_id).instructions


def catalogue() -> str:
    """One line per skill, for the router prompt."""
    return "\n".join(f"- {s.summary_line()}" for s in list_skills())


__all__ = ["SKILLS", "Skill", "SkillError", "DEFINITIONS_DIR", "FALLBACK_SKILL_ID",
           "list_skills", "get_skill", "get_instructions", "catalogue",
           "load_all", "load_skill", "parse_frontmatter"]
