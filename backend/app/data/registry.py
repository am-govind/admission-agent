"""Center / region registry built from distinct values in the loaded data.

Resolves loose user input ("Pune", "panvel") to canonical names, and reports ambiguity
so the agent can ask instead of guessing.

Centers are named by city: "Pune - FC Road Vidyapeeth", "Nagpur Vidyapeeth". A term that
matches several centers of the *same* city is therefore not ambiguous at all — "Pune"
means the six Pune centers, and asking which one was meant is the wrong question when the
user said "all centres across Pune". Such a term resolves to a `city` group that
aggregates. A term matching centers in *different* cities ("Kalyan", which appears in both
Dombivali and Mumbai) is genuinely ambiguous and still asks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.database import execute, table_exists
from .schema import TABLE_RD26


@dataclass
class Resolution:
    kind: str                       # "center" | "city" | "region" | "ambiguous" | "none"
    value: str | None = None
    region: str | None = None
    candidates: list[str] = field(default_factory=list)
    # For kind == "city": the centers the group covers.
    members: list[str] = field(default_factory=list)


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


def city_of(center: str) -> str:
    """The city a center belongs to, from its name.

    "Pune - FC Road Vidyapeeth" -> "Pune"; "Nagpur Vidyapeeth" -> "Nagpur". Names with
    no " - " fall back to the first word, which is right for the single-center cities
    ("Vijayawada Vidyapeeth") and harmless for the few multi-word ones
    ("Chhatrapati Sambhajinagar Vidyapeeth" -> "Chhatrapati"), because a lone match
    resolves as a center before any city grouping is considered.
    """
    head = center.split(" - ")[0].strip() if " - " in center else center.split(" ")[0]
    return head.strip()


def resolve(term: str | None) -> Resolution:
    """Resolve a free-text location term against known centers, cities and regions."""
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
        cities = {city_of(c) for c, _ in matches}
        if len(cities) == 1:
            city = cities.pop()
            city_regions = {r for _, r in matches}
            return Resolution(
                kind="city", value=city,
                # One region per city in this data; left blank if that ever changes so
                # the scope filters on the center list alone rather than on a guess.
                region=city_regions.pop() if len(city_regions) == 1 else None,
                members=[c for c, _ in matches])
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


def centers_in_city(city: str) -> list[str]:
    needle = city.strip().lower()
    return [c for c, _ in _distinct_centers() if city_of(c).lower() == needle]


def all_cities() -> list[str]:
    """Distinct city names, for prompts and for the explorer's vocabulary."""
    return sorted({city_of(c) for c, _ in _distinct_centers()})


def region_of(center: str) -> str | None:
    for c, r in _distinct_centers():
        if c == center:
            return r
    return None
