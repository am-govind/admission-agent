"""Google Sheets ingestion source.

Reads each tab in fixed-size row windows rather than one request, because the Sheets
API caps a single response and a 40k-row tab will not fit. Transient failures
(429/5xx) are retried with exponential backoff plus jitter; anything else is raised
so the refresh is recorded as failed instead of quietly loading a partial table.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Iterator, Sequence

from ...core.config import settings
from ..schema import TABLE_TAB_SETTING
from .base import SheetSource, SourceError, TableRead

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _col_letter(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _quote_tab(tab: str) -> str:
    return "'" + tab.replace("'", "''") + "'"


class GoogleSheetsSource(SheetSource):
    name = "gsheets"

    def __init__(self) -> None:
        if not settings.gsheet_id or settings.gsheet_id.startswith("PUT_"):
            raise SourceError(
                "DATA_SOURCE=gsheets but GSHEET_ID is not set. Put the spreadsheet ID "
                "(the part of the URL between /d/ and /edit) in GSHEET_ID.")
        creds_path = settings.google_application_credentials
        if not creds_path:
            raise SourceError(
                "DATA_SOURCE=gsheets but GOOGLE_APPLICATION_CREDENTIALS is not set.")
        self._sheet = self._build(creds_path)
        self._titles = self._tab_titles()

    # ---------- setup ----------
    def _build(self, creds_path: str):
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as e:
            raise SourceError(
                "Google client libraries are missing. Install google-api-python-client "
                "and google-auth.") from e

        try:
            with open(creds_path, encoding="utf-8") as fh:
                json.load(fh)
        except FileNotFoundError as e:
            raise SourceError(f"Service account file not found: {creds_path}") from e
        except json.JSONDecodeError as e:
            raise SourceError(
                f"Service account file {creds_path} is not valid JSON ({e}). Re-download "
                "the key from Google Cloud; the private_key value must be a single line "
                "with literal \\n escapes.") from e

        try:
            creds = Credentials.from_service_account_file(creds_path, scopes=_SCOPES)
        except Exception as e:  # noqa: BLE001 - malformed key material surfaces many ways
            raise SourceError(
                f"Could not build credentials from {creds_path}: {e}") from e
        return build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()

    def _tab_titles(self) -> set[str]:
        meta = self._call(lambda: self._sheet.get(
            spreadsheetId=settings.gsheet_id, fields="sheets.properties.title").execute())
        return {s["properties"]["title"] for s in meta.get("sheets", [])}

    # ---------- request plumbing ----------
    def _call(self, fn):
        """Run one API call, retrying rate limits and server errors."""
        from googleapiclient.errors import HttpError

        attempts = max(1, settings.sheets_max_retries)
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status not in _RETRY_STATUS or attempt == attempts:
                    raise SourceError(f"Google Sheets API error {status}: {e}") from e
                delay = min(30.0, 2 ** attempt) + random.uniform(0, 1)
                log.warning("Sheets API %s, retry %s/%s in %.1fs", status, attempt,
                            attempts, delay)
                time.sleep(delay)
            except OSError as e:
                if attempt == attempts:
                    raise SourceError(f"Network error talking to Google Sheets: {e}") from e
                time.sleep(min(30.0, 2 ** attempt) + random.uniform(0, 1))
        raise SourceError("Google Sheets API call failed")

    def _values(self, rng: str) -> list[list[Any]]:
        res = self._call(lambda: self._sheet.values().get(
            spreadsheetId=settings.gsheet_id,
            range=rng,
            # Numbers must arrive unformatted (no thousands separators, no currency
            # symbols) while dates arrive as text rather than serial numbers.
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="FORMATTED_STRING",
        ).execute())
        return res.get("values", [])

    # ---------- source interface ----------
    def read_table(self, table: str) -> TableRead | None:
        tab = getattr(settings, TABLE_TAB_SETTING[table], "")
        if not tab:
            return None
        if tab not in self._titles:
            log.info("Tab %r not present in the spreadsheet; %s will be unavailable",
                     tab, table)
            return None

        quoted = _quote_tab(tab)
        header_rows = self._values(f"{quoted}!1:1")
        if not header_rows or not header_rows[0]:
            return None
        header = header_rows[0]
        last_col = _col_letter(len(header))
        return TableRead(header=header, windows=self._windows(quoted, last_col), tab=tab)

    def _windows(self, quoted_tab: str, last_col: str) -> Iterator[Sequence[Sequence[Any]]]:
        batch = max(1, settings.sheets_batch_rows)
        start = 2
        while True:
            end = start + batch - 1
            rows = self._values(f"{quoted_tab}!A{start}:{last_col}{end}")
            if not rows:
                return
            yield rows
            # A short window means the tab ended inside it.
            if len(rows) < batch:
                return
            start += batch
