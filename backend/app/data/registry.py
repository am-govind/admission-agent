"""Center / region registry built from distinct values in the loaded data.

Resolves loose user input ("Pune", "panvel") to canonical names, and reports
ambiguity so the agent can ask instead of guessing. "Pune" matches five centers and
must not silently become one of them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.database import execute, table_exists
from .schema import TABLE_RD26


@dataclass
class Resolution:
    kind: str                       # "center" | "region" | "ambiguous" | "none"
    value: str | None = None
    region: str | None = None
    candidates: list[str] = field(default_factory=list)


def _distinct_centers() -> list[tuple[str, str]]:
    if not table_exists(TABLE_RD26):
        return []
    return [(r[0], r[1]) for r in execute(
        f"SELECT DISTINCT center, region FROM {TABLE_RD26} "
        "WHERE center IS NOT NULL AND region IS NOT NULL ORDER BY center")]


def _distinct_regions() -> list[str]:
    if not table_exists(TABLE_RD26):
        return []
    return [r[0] for r in execute(
        f"SELECT DISTINCT region FROM {TABLE_RD26} WHERE region IS NOT NULL ORDER BY region")]


def resolve(term: str | None) -> Resolution:
    """Resolve a free-text location term against known centers and regions."""
    if not term or not term.strip():
        return Resolution(kind="none")
    needle = term.strip().lower()

    regions = _distinct_regions()
    centers = _distinct_centers()

    # Exact matches win outright: "Nagpur Vidyapeeth" must not be treated as an
    # ambiguous prefix of "Nagpur Vidyapeeth (Residential Program)".
    for region in regions:
        if needle == region.lower():
            return Resolution(kind="region", value=region, region=region)
    for center, region in centers:
        if needle == center.lower():
            return Resolution(kind="center", value=center, region=region)

    matches = [(c, r) for c, r in centers if needle in c.lower()]
    if len(matches) == 1:
        return Resolution(kind="center", value=matches[0][0], region=matches[0][1])
    if len(matches) > 1:
        return Resolution(kind="ambiguous", candidates=[c for c, _ in matches])

    region_matches = [r for r in regions if needle in r.lower()]
    if len(region_matches) == 1:
        return Resolution(kind="region", value=region_matches[0], region=region_matches[0])
    if len(region_matches) > 1:
        return Resolution(kind="ambiguous", candidates=region_matches)

    return Resolution(kind="none", candidates=[c for c, _ in centers][:10])


def all_centers() -> list[str]:
    return [c for c, _ in _distinct_centers()]


def all_regions() -> list[str]:
    return _distinct_regions()


def centers_in_region(region: str) -> list[str]:
    return [c for c, r in _distinct_centers() if r == region]


def region_of(center: str) -> str | None:
    for c, r in _distinct_centers():
        if c == center:
            return r
    return None
