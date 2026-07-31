"""Pivoting several single-series results into one multi-series result.

A comparison is one chart. Two charts side by side force the reader to compare axes
before they can compare numbers, and the axes are rarely the same; one chart with two
coloured lines answers "which is higher" at a glance. The frontend already renders any
number of series from `ChartSpec.y`, so merging is entirely a backend concern.

The same pivot serves two callers, which is why it lives here rather than in either of
them: `admissions.compare_series` merges the series it deliberately queried, and
`agent.runtime` merges compatible results when the model asked for each scope separately
instead. Both must produce an identical shape, and one implementation is the only way to
be sure of that.
"""
from __future__ import annotations

from .result import ChartSpec, Provenance, ToolResult, jsonable

# Rows that aggregate the others; charting them alongside their own components would
# dwarf every real bar, and merging them across series is meaningless.
TOTAL_LABELS = frozenset({"grand total", "subtotal", "total"})


def series_label(result: ToolResult) -> str:
    """The name a result's series should carry in a merged chart."""
    scope = result.values.get("scope")
    if isinstance(scope, str) and scope.strip():
        return scope.strip()
    if result.provenance is not None and result.provenance.scope:
        return result.provenance.scope
    return result.metric


def mergeable(results: list[ToolResult]) -> bool:
    """Whether these results describe the same axis measured over different scopes."""
    if len(results) < 2:
        return False
    first = results[0]
    if first.chart is None or len(first.columns) != 2:
        return False
    labels = set()
    for result in results:
        if not result.ok or not result.has_table or result.chart is None:
            return False
        if len(result.columns) != 2 or result.metric != first.metric:
            return False
        if (result.chart.x, result.chart.kind) != (first.chart.x, first.chart.kind):
            return False
        if result.columns[0] != first.columns[0]:
            return False
        labels.add(series_label(result))
    # Colliding labels mean the same scope twice: nothing to compare, and a merged
    # chart would silently drop one of the two columns.
    return len(labels) == len(results)


def merge(results: list[ToolResult], *, title: str | None = None) -> ToolResult | None:
    """One wide result: columns [x, label1, label2, ...] and one chart per label.

    Returns None when the results are not comparable, so callers can fall back to
    rendering them separately rather than inventing an axis.

    A value present in one series and missing from another becomes None, which the chart
    renders as a gap rather than as a zero it cannot justify.
    """
    if not mergeable(results):
        return None

    first = results[0]
    x_column = first.columns[0]
    labels = [series_label(r) for r in results]

    per_label: dict[str, dict[str, object]] = {}
    totals: dict[str, float] = {}
    axis = _Axis()

    for label, result in zip(labels, results):
        values: dict[str, object] = {}
        total = 0.0
        body = [row for row in result.rows
                if str(jsonable(row[0])).lower() not in TOTAL_LABELS]
        for position, row in enumerate(body):
            key = axis.add(row[0], from_end=len(body) - 1 - position)
            values[key] = row[1]
            if isinstance(row[1], (int, float)):
                total += float(row[1])
        per_label[label] = values
        totals[label] = total

    # Series with no x value in common are not being compared at anything; one chart of
    # two disjoint halves is strictly worse than two charts. Center leaderboards for two
    # different regions are the case this catches.
    shared = set.intersection(*(set(v) for v in per_label.values()))
    if not shared:
        return None

    rows = [[value, *(per_label[label].get(key) for label in labels)]
            for key, value in axis.ordered()]
    if not rows:
        return None

    chart_title = title or f"{_base_title(first)} — {' vs '.join(labels)}"
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    leader = ranked[0]
    summary = (f"Comparing {', '.join(labels)} across {len(rows)} "
               f"{x_column.lower()} values: "
               + "; ".join(f"{label} {_fmt(total)}" for label, total in totals.items())
               + f". {leader[0]} leads.")

    return ToolResult(
        metric=first.metric,
        summary=summary,
        values={"scope": " vs ".join(labels), "series": labels,
                "totals": {label: totals[label] for label in labels},
                "leader": leader[0]},
        columns=[x_column, *labels],
        rows=rows,
        chart=ChartSpec(kind=first.chart.kind, x=x_column, y=labels, title=chart_title),
        provenance=_merged_provenance(results, labels),
    )


class _Axis:
    """The shared x axis of a merged chart, ordered by distance from the newest value.

    Every series here is anchored at the same reference date, so "three rows from the
    end" means the same thing in each of them. Ordering by that distance therefore lines
    up windows of different lengths correctly: a 6-day series and a 3-day series ending
    on the same day interleave chronologically instead of the shorter one's dates being
    appended after the longer one's. Where the series carry identical x values — the
    usual case — this reproduces their original order exactly, which is what keeps
    workbook class ordering intact.
    """

    def __init__(self) -> None:
        self._values: dict[str, object] = {}
        self._from_end: dict[str, int] = {}
        self._first_seen: dict[str, int] = {}

    def add(self, value: object, *, from_end: int) -> str:
        key = str(jsonable(value))
        self._values.setdefault(key, value)
        self._first_seen.setdefault(key, len(self._first_seen))
        self._from_end[key] = max(self._from_end.get(key, -1), from_end)
        return key

    def ordered(self) -> list[tuple[str, object]]:
        keys = sorted(self._from_end,
                      key=lambda k: (-self._from_end[k], self._first_seen[k]))
        return [(k, self._values[k]) for k in keys]


def _fmt(total: float) -> str:
    return f"{int(total):,}" if float(total).is_integer() else f"{total:,.2f}"


def _base_title(result: ToolResult) -> str:
    """The chart title with its single-scope suffix stripped, ready to be re-suffixed."""
    title = result.chart.title if result.chart else ""
    return title.split(" — ")[0] if " — " in title else (title or result.metric)


def _merged_provenance(results: list[ToolResult], labels: list[str]) -> Provenance:
    """One provenance covering every series, so each scope stays auditable."""
    first = results[0].provenance
    tables: list[str] = []
    notes: list[str] = []
    row_count = 0
    for label, result in zip(labels, results):
        source = result.provenance
        if source is None:
            continue
        for table in source.source_tables:
            if table not in tables:
                tables.append(table)
        notes.append(f"{label}: {' AND '.join(source.filters) or 'no filters'}")
        row_count += source.row_count or 0
    return Provenance(
        metric=results[0].metric,
        source_tables=tables,
        filters=[],
        reference_date=first.reference_date if first else None,
        scope=" vs ".join(labels),
        row_count=row_count,
        notes=notes,
    )
