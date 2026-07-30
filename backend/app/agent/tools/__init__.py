"""Agent-callable tools.

Importing this package registers every tool. Each wrapper is one line delegating to
analytics; if a wrapper grows a branch or a threshold, the logic has leaked out of the
audited layer and tests/test_tools.py will fail.
"""
from __future__ import annotations

from . import admissions_tools, explorer_tools, finance_tools  # noqa: F401
from .registry import REGISTRY, Tool, all_names, get_tool, schemas_for, tool

__all__ = ["REGISTRY", "Tool", "all_names", "get_tool", "schemas_for", "tool"]
