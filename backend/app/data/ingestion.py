"""Ingestion entry point.

`refresh()` is called by the scheduler and by POST /admin/refresh. It picks the
Google Sheets path when configured, otherwise falls back to synthetic sample data
so the app is always usable. Tables are REPLACED (no snapshots — trends come from
the joining_date column).
"""
from __future__ import annotations

import os

from ..core.config import settings
from .excel import load_from_excel
from .google_sheets import load_from_google_sheets
from .sample_data import load_sample_data


def refresh() -> dict[str, int]:
    # 1) If an Excel file exists (e.g. TRY.xlsx), load directly from Excel
    if settings.excel_file_path and os.path.exists(settings.excel_file_path):
        try:
            return load_from_excel(settings.excel_file_path)
        except Exception as e:
            pass

    try:
        return load_from_excel()
    except Exception:
        pass

    # 2) Google Sheets if configured
    if not settings.use_sample_data and settings.gsheet_id and not settings.gsheet_id.startswith("PUT_"):
        try:
            return load_from_google_sheets()
        except Exception:  # noqa: BLE001
            pass

    # 3) Synthetic sample data fallback
    return load_sample_data()

