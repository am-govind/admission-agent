"""Input guardrails — block obvious prompt-injection / jailbreak attempts."""
from __future__ import annotations

import re

from ..core.config import settings
from .errors import GuardrailError

_INJECTION_PATTERNS = [
    r"ignore (all|previous|the above).{0,20}instructions",
    r"disregard (all|previous|the)",
    r"you are now",
    r"system prompt",
    r"reveal.{0,20}(prompt|instructions|system)",
    r"act as .{0,30}(dan|jailbreak)",
]


def scan_input(text: str) -> None:
    """Raise GuardrailError if the input looks like an injection/jailbreak."""
    if not settings.guardrails_enabled:
        return
    low = text.lower()
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, low):
            raise GuardrailError("Your request was blocked by input safety checks.")
