"""Guardrail error types."""
from __future__ import annotations


class GuardrailError(Exception):
    """Raised when a request is blocked by an input guardrail."""
