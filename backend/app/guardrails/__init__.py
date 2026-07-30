"""Guardrails — cross-cutting input/output safety.

Public surface used by the streaming and API layers:
  - GuardrailError : raised when input is blocked
  - scan_input     : block prompt-injection / jailbreak attempts
  - scan_output    : mask any residual PII (student names, registration numbers)

If `llm-guard` is installed and enabled it can be wired in here; otherwise a
lightweight built-in fallback runs so the app works with no heavy model downloads.
"""
from __future__ import annotations

from .errors import GuardrailError
from .input_scanners import scan_input
from .output_scanners import scan_output

__all__ = ["GuardrailError", "scan_input", "scan_output"]
