"""Output guardrails — mask any residual PII in model output (defense in depth)."""
from __future__ import annotations

import re

from ..core.config import settings

# Registration numbers show up as long digit runs; mask them if they leak.
_REGNO_RE = re.compile(r"\b\d{8,}\b")


def scan_output(text: str) -> str:
    """Mask any residual PII in model output."""
    if not settings.guardrails_enabled:
        return text
    return _REGNO_RE.sub("•••", text)
