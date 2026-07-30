"""Test isolation.

Every path setting is redirected into a temp directory *before* app.core.config is
imported, because settings is a module-level singleton read once at import time. Without
this, running the suite would overwrite the developer's real DuckDB and SQLite files.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="admission-agent-tests-"))

# Environment variables win over backend/.env in pydantic-settings, so this holds even
# on a machine configured to point at Google Sheets.
os.environ.update({
    "DUCKDB_PATH": str(TMP / "analytics.duckdb"),
    "APPDB_PATH": str(TMP / "app.sqlite3"),
    "LEGACY_DUCKDB_PATH": str(TMP / "absent-legacy.duckdb"),
    "DATA_SOURCE": "sample",
    "LLM_API_KEY": "",
    "GUARDRAILS_ENABLED": "true",
    "REFRESH_ON_STARTUP_IF_EMPTY": "false",
    "ALERT_EMAIL_ENABLED": "false",
})


@pytest.fixture(scope="session", autouse=True)
def dataset():
    """Load the synthetic dataset once for the whole session."""
    from app.core.config import settings
    from app.data import ingestion

    assert settings.duckdb_file.parent == TMP, (
        f"tests must not touch the real database (got {settings.duckdb_file})")

    result = ingestion.refresh("sample")
    assert not result.failed, f"sample ingestion failed: {result.failed}"
    yield result
    shutil.rmtree(TMP, ignore_errors=True)


@pytest.fixture
def conversation_id():
    """A fresh conversation, so memory slots never leak between tests."""
    from app.agent import memory
    from app.data import conversation

    cid = conversation.new_conversation("tester")
    yield cid
    memory.clear(cid)
