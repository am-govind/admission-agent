"""Center / region registry built from distinct values in the data.

Used to resolve loose user input ("Pune", "mumbai") to canonical center/region
names, and to drive clarifying questions when a term is ambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.database import execute
from .schema import TABLE_RD26


@dataclass
class Resolution:
    kind: str                     # "center" | "region" | "ambiguous" | "none"
    value: str | None = None
    region: str | None = None
    candidates: list[str] | None = None


def _distinct_centers() -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in execute(
        f"SELECT DISTINCT center, region FROM {TABLE_RD26} WHERE center IS NOT NULL")]


def _distinct_regions() -> list[str]:
    return [r[0] for r in execute(
        f"SELECT DISTINCT region FROM {TABLE_RD26} WHERE region IS NOT NULL")]


def resolve(term: str | None) -> Resolution:
    """Resolve a free-text location term against known centers/regions."""
    if not term:
        return Resolution(kind="none")
    t = term.strip().lower()

    regions = _distinct_regions()
    for reg in regions:
        if t == reg.lower():
            return Resolution(kind="region", value=reg, region=reg)

    centers = _distinct_centers()
    for center, region in centers:
        if t == center.lower():
            return Resolution(kind="center", value=center, region=region)

    matches = [(c, r) for c, r in centers if t in c.lower()]
    if len(matches) == 1:
        return Resolution(kind="center", value=matches[0][0], region=matches[0][1])
    if len(matches) > 1:
        return Resolution(kind="ambiguous", candidates=[c for c, _ in matches])

    reg_matches = [r for r in regions if t in r.lower()]
    if len(reg_matches) == 1:
        return Resolution(kind="region", value=reg_matches[0], region=reg_matches[0])
    if len(reg_matches) > 1:
        return Resolution(kind="ambiguous", candidates=reg_matches)

    return Resolution(kind="none", candidates=[c for c, _ in centers][:10])


def all_centers() -> list[str]:
    return [c for c, _ in _distinct_centers()]


def all_regions() -> list[str]:
    return _distinct_regions()
