"""Ingestion sources. Exactly one is active per refresh, chosen by DATA_SOURCE."""
from __future__ import annotations

from ...core.config import settings
from .base import SheetSource, SourceError, TableRead

__all__ = ["SheetSource", "SourceError", "TableRead", "get_source"]


def get_source(name: str | None = None) -> SheetSource:
    """Build the configured source. Unknown names fail loudly, never silently."""
    resolved = (name or settings.data_source or "").strip().lower()
    if resolved == "gsheets":
        from .google_sheets import GoogleSheetsSource
        return GoogleSheetsSource()
    if resolved == "excel":
        from .excel import ExcelSource
        return ExcelSource()
    if resolved == "sample":
        from .sample import SampleSource
        return SampleSource()
    raise SourceError(
        f"Unknown DATA_SOURCE {resolved!r}. Expected one of: gsheets, excel, sample.")
