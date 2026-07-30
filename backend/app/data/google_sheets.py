"""Google Sheets ingestion path (used when USE_SAMPLE_DATA=false + credentials exist)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..core.config import settings
from ..core.database import _lock, get_conn
from .schema import TABLE_FINANCE, TABLE_RD25, TABLE_RD26, TABLE_TARGETS


def load_from_google_sheets() -> dict[str, int]:
    """Pull tabs from Google Sheets into DuckDB. Requires google libs + credentials."""
    from google.oauth2.service_account import Credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore

    creds = Credentials.from_service_account_file(
        settings.google_application_credentials,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    try:
        creds.refresh(Request())
    except Exception:
        pass
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    def read_tab(tab: str) -> list[list[Any]]:
        res = sheet.values().get(spreadsheetId=settings.gsheet_id, range=tab).execute()
        return res.get("values", [])

    conn = get_conn()
    counts: dict[str, int] = {}
    mapping = {TABLE_RD26: settings.tab_rd26, TABLE_RD25: settings.tab_rd25,
               TABLE_FINANCE: settings.tab_finance, TABLE_TARGETS: settings.tab_targets}
    with _lock:
        for table, tab in mapping.items():
            try:
                values = read_tab(tab)
            except Exception as e:
                # If the tab doesn't exist, skip it (except for the main RD26 table)
                if table == TABLE_RD26:
                    raise e
                continue
            if not values:
                continue
            header, *data = values
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            
            # Using CSV file load to bypass Python loop overhead for massive datasets
            import csv
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w', newline='', encoding='utf-8', delete=False) as tmp:
                writer = csv.writer(tmp)
                writer.writerow(header)
                # Fill missing column cells
                for row in data:
                    writer.writerow((row + [None] * len(header))[: len(header)])
                tmp_path = tmp.name
                
            try:
                # DuckDB native CSV reader automatically infers and streams the load instantly
                conn.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto('{tmp_path.replace(os.sep, '/')}')")
                counts[table] = len(data)
                
                # Strip commas, spaces, and currency symbols from numeric/currency columns
                for col_desc in conn.execute(f"SELECT * FROM {table} LIMIT 0").description:
                    col_name = col_desc[0]
                    col_lower = col_name.lower()
                    if col_lower in {"fees_amt", "fees_paid", "arpu", "pct_discount", "pct_paid", "enrolled_years"} or col_lower.endswith("_target") or col_lower.endswith("_amt") or col_lower.endswith("_paid"):
                        try:
                            conn.execute(f"UPDATE {table} SET {col_name} = trim(replace(replace(replace(CAST({col_name} AS VARCHAR), ',', ''), '₹', ''), '$', '')) WHERE {col_name} IS NOT NULL")
                        except Exception:
                            pass
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_refresh', ?)",
                     [dt.datetime.now().isoformat()])
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('source', 'gsheets')")
    return counts
