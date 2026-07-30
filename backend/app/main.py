"""FastAPI application factory.

Layers (top → bottom):
  api/         HTTP routes (thin)
  agent/       the AI engine: router → skills → tools, prompts
  guardrails/  cross-cutting input/output safety (injection block, PII mask)
  analytics/   sealed 'blackbox' business logic (pure DuckDB functions)
  data/        ingestion, reference date, registry, conversation store, schema
  core/        config, database connection, security
  streaming/   self-contained SSE (renderState + JSON Patch)
"""
from __future__ import annotations

import asyncio
import datetime as dt
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, auth, chat
from .core import security
from .core.config import settings
from .core.database import execute
from .data import ingestion
from .data.schema import TABLE_RD26


async def _daily_refresh_loop() -> None:
    """Lightweight morning refresh at ~06:00 local (no external scheduler dependency)."""
    while True:
        now = dt.datetime.now()
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            ingestion.refresh()
        except Exception:  # noqa: BLE001
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    security.bootstrap_admin()
    rows = execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [TABLE_RD26])
    if not rows or rows[0][0] == 0:
        ingestion.refresh()
    task = asyncio.create_task(_daily_refresh_loop())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="Admissions & Finance AI Agent", version="2.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    return app


app = create_app()
