"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to backend/ so the app can be launched from any working directory.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8500
    cors_origins: str = "http://localhost:5173"

    # Auth
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 720
    bootstrap_admin_user: str = "admin"
    bootstrap_admin_password: str = "admin123"

    # Data
    duckdb_path: str = "./data/app.duckdb"
    use_sample_data: bool = True
    excel_file_path: str = "../TRY.xlsx"

    # Google Sheets
    gsheet_id: str = ""
    google_application_credentials: str = ""
    tab_rd26: str = "RD26_DUMP"
    tab_rd25: str = "RD25_DUMP"
    tab_finance: str = "Finance Dump"
    tab_targets: str = "Targets"

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
