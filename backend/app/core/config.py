"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to backend/ so the app can be launched from any working directory.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _BACKEND_ROOT / ".env"


def _resolve(raw: str) -> Path:
    """Relative paths are anchored to backend/, not the process working directory.

    Without this, launching from the repo root and from backend/ would silently
    create two different database files.
    """
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (_BACKEND_ROOT / path).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8500
    cors_origins: str = "http://localhost:5173"

    # Logging
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    # Empty means console only. A relative path is anchored to backend/.
    log_file: str = ""
    log_max_bytes: int = 10_485_760
    log_backup_count: int = 5

    # Auth
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 720
    bootstrap_admin_user: str = "admin"
    bootstrap_admin_password: str = "admin123"

    # Storage — analytics is replaced wholesale by every refresh, so durable app
    # state (users, chat, memory, audit) lives in a separate SQLite file.
    duckdb_path: str = "./data/analytics.duckdb"
    appdb_path: str = "./data/app.sqlite3"
    # Pre-split single-file database, read once by core.migrate.
    legacy_duckdb_path: str = "./data/app.duckdb"

    # Ingestion — exactly one source, chosen explicitly. No silent fallbacks.
    data_source: Literal["gsheets", "excel", "sample"] = "sample"
    excel_file_path: str = "../TRY.xlsx"

    # Google Sheets
    gsheet_id: str = ""
    google_application_credentials: str = ""
    tab_rd26: str = "RD26_DUMP"
    tab_rd25: str = "RD25_DUMP"
    tab_finance: str = "Finance Dump"
    tab_targets: str = "Targets"
    # The API caps a single response near 10MB; 5000 rows x 21 columns stays well under.
    sheets_batch_rows: int = 5000
    sheets_max_retries: int = 3

    # Daily refresh
    refresh_at: str = "08:30"
    refresh_tz: str = "Asia/Kolkata"
    refresh_poll_seconds: int = 900
    refresh_on_startup_if_empty: bool = True

    # Agent
    agent_max_tool_iterations: int = 5
    explorer_max_rows: int = 200
    memory_verbatim_turns: int = 10

    # LLM — any OpenAI-compatible endpoint (GitHub Models, HF router, Ollama, vLLM)
    llm_base_url: str = "https://models.github.ai/inference"
    llm_model: str = "openai/gpt-4.1"
    llm_api_key: str = Field("", validation_alias=AliasChoices("LLM_API_KEY", "GITHUB_TOKEN"))
    # Omitted from the request when unset — reasoning models (e.g. gpt-5) reject a custom value.
    llm_temperature: float | None = None
    # Disable for providers that reject or ignore response_format (e.g. Scaleway).
    llm_json_mode: bool = True

    # Guardrails
    guardrails_enabled: bool = True

    # Alerts
    alert_email_enabled: bool = False
    alert_email_to: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "agent@example.com"

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, v: str) -> str:
        level = v.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}, got {v!r}")
        return level

    @field_validator("refresh_at")
    @classmethod
    def _check_refresh_at(cls, v: str) -> str:
        try:
            dt.datetime.strptime(v.strip(), "%H:%M")
        except ValueError as e:
            raise ValueError(f"REFRESH_AT must be HH:MM (24-hour), got {v!r}") from e
        return v.strip()

    @field_validator("refresh_tz")
    @classmethod
    def _check_refresh_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v.strip())
        except Exception as e:  # noqa: BLE001 - ZoneInfoNotFoundError plus OS variants
            raise ValueError(f"REFRESH_TZ is not a known IANA timezone: {v!r}") from e
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def log_file_path(self) -> Path | None:
        return _resolve(self.log_file) if self.log_file.strip() else None

    @property
    def duckdb_file(self) -> Path:
        return _resolve(self.duckdb_path)

    @property
    def appdb_file(self) -> Path:
        return _resolve(self.appdb_path)

    @property
    def legacy_duckdb_file(self) -> Path:
        return _resolve(self.legacy_duckdb_path)

    @property
    def excel_file(self) -> Path:
        return _resolve(self.excel_file_path)

    @property
    def refresh_zone(self) -> ZoneInfo:
        return ZoneInfo(self.refresh_tz)

    @property
    def refresh_time(self) -> dt.time:
        parsed = dt.datetime.strptime(self.refresh_at, "%H:%M")
        return dt.time(parsed.hour, parsed.minute)


settings = Settings()
