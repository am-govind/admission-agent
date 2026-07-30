"""SKILL.md parsing.

A skill is data, not code: a directory containing SKILL.md, whose YAML frontmatter
declares the metadata and whose markdown body is the instruction text injected into
the prompt. Adding a capability is a new directory; changing how the agent talks about
one is a markdown edit that cannot break the app.

Validation is strict and happens at import. A misspelled key or tool name silently
disables a capability, which is far harder to notice later than a startup failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SKILL_FILENAME = "SKILL.md"

_FRONTMATTER = re.compile(r"^---\s*\n(?P<yaml>.*?)\n---\s*(?:\n|$)", re.DOTALL)

_ALLOWED_TOP = {"name", "description", "metadata"}
_ALLOWED_META = {"required_tool_names", "optional_tool_names", "intents", "triggers"}


class SkillError(Exception):
    """A SKILL.md file is malformed."""


@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    description: str
    instructions: str
    required_tool_names: tuple[str, ...] = ()
    optional_tool_names: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    path: Path | None = field(default=None, compare=False)

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Required first: order is what the model sees in the schema list."""
        seen: dict[str, None] = {}
        for name in (*self.required_tool_names, *self.optional_tool_names):
            seen.setdefault(name, None)
        return tuple(seen)

    def summary_line(self) -> str:
        return f"{self.skill_id}: {self.description}"


def parse_frontmatter(text: str, origin: str = "<string>") -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        raise SkillError(f"{origin}: missing YAML frontmatter delimited by --- lines")
    try:
        data = yaml.safe_load(match.group("yaml")) or {}
    except yaml.YAMLError as e:
        raise SkillError(f"{origin}: frontmatter is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise SkillError(f"{origin}: frontmatter must be a mapping")
    return data, text[match.end():].strip()


def _string_list(value: Any, origin: str, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise SkillError(f"{origin}: {key} must be a list of strings")
    return tuple(v.strip() for v in value if v.strip())


def load_skill(directory: Path) -> Skill:
    path = directory / SKILL_FILENAME
    if not path.exists():
        raise SkillError(f"{directory}: no {SKILL_FILENAME}")
    origin = f"{directory.name}/{SKILL_FILENAME}"

    data, body = parse_frontmatter(path.read_text(encoding="utf-8"), origin)

    unknown = set(data) - _ALLOWED_TOP
    if unknown:
        raise SkillError(f"{origin}: unknown frontmatter key(s): {', '.join(sorted(unknown))}")

    name = data.get("name")
    description = data.get("description")
    for key, value in (("name", name), ("description", description)):
        if not isinstance(value, str) or not value.strip():
            raise SkillError(f"{origin}: {key} is required and must be a non-empty string")
    if not body:
        raise SkillError(f"{origin}: the markdown body (the instructions) is empty")

    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise SkillError(f"{origin}: metadata must be a mapping")
    unknown_meta = set(metadata) - _ALLOWED_META
    if unknown_meta:
        raise SkillError(
            f"{origin}: unknown metadata key(s): {', '.join(sorted(unknown_meta))}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_META))}")

    required = _string_list(metadata.get("required_tool_names"), origin,
                            "required_tool_names")
    optional = _string_list(metadata.get("optional_tool_names"), origin,
                            "optional_tool_names")
    overlap = set(required) & set(optional)
    if overlap:
        raise SkillError(
            f"{origin}: tool(s) listed as both required and optional: "
            f"{', '.join(sorted(overlap))}")

    return Skill(
        skill_id=directory.name,
        name=name.strip(),                      # type: ignore[union-attr]
        description=description.strip(),        # type: ignore[union-attr]
        instructions=body,
        required_tool_names=required,
        optional_tool_names=optional,
        intents=_string_list(metadata.get("intents"), origin, "intents"),
        triggers=tuple(t.lower() for t in _string_list(
            metadata.get("triggers"), origin, "triggers")),
        path=path,
    )


def load_all(root: Path) -> dict[str, Skill]:
    """Load every skill directory under root, sorted by id for stable prompt order."""
    if not root.exists():
        raise SkillError(f"skill definitions directory not found: {root}")
    skills: dict[str, Skill] = {}
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (directory / SKILL_FILENAME).exists():
            continue
        skill = load_skill(directory)
        skills[skill.skill_id] = skill
    if not skills:
        raise SkillError(f"no {SKILL_FILENAME} files found under {root}")
    return skills
