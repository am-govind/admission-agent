"""Sealed analytics — the only layer that computes numbers.

Pure Python over DuckDB, with no knowledge that an LLM exists. Every function returns
a ToolResult carrying provenance, and every threshold it applies is declared once in
filters.py. The tool layer above wraps these one-to-one; it must not contain logic.
"""
from __future__ import annotations

from . import (admissions, cancellations, explorer, filters, finance, retention,
               revenue, rollups)
from .result import ChartSpec, Provenance, ToolResult

__all__ = [
    "admissions", "cancellations", "explorer", "filters", "finance", "retention",
    "revenue", "rollups", "ChartSpec", "Provenance", "ToolResult",
]
