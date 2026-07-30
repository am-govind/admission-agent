"""FastAPI application factory.

Layers (top → bottom):
  api/         HTTP routes (thin)
  agent/       router → skills → tools → the answering loop, prompts, memory
  guardrails/  cross-cutting input/output safety (injection block, PII mask)
  analytics/   sealed business logic (pure typed functions over DuckDB)
  data/        ingestion, sources, availability, reference date, registry, schema
  core/        config, DuckDB (analytics), SQLite (app state), security
  streaming/   self-contained SSE (renderState + JSON Patch)
"""
from __future__ import annotations

import asyncio
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, auth, chat
from .core import migrate, security
from .core.config import settings
from .data import availability, ingestion
from .data.schema import TABLE_RD26

log = logging.getLogger(__name__)


async def _refresh_scheduler() -> None:
    """Catch-up scheduler for the daily refresh.

    Polls instead of sleeping until a wall-clock time, and decides what to do by
    comparing the persisted last-success against the most recent elapsed cutoff. That
    makes it restart-safe: a process that was down at 08:30 refreshes as soon as it is
    back, and one that was up refreshes exactly once.
    """
    while True:
        try:
            if availability.refresh_due():
                log.info("Scheduled refresh is due; starting")
                # Ingestion is blocking and CPU/IO bound, so it must not run on the loop.
                await asyncio.to_thread(ingestion.run_refresh, "scheduled")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the scheduler must outlive any single failure
            log.exception("Refresh scheduler iteration failed")
        await asyncio.sleep(max(30, settings.refresh_poll_seconds))


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate.migrate_app_state()
    security.bootstrap_admin()

    if settings.refresh_on_startup_if_empty and not availability.is_available(TABLE_RD26):
        log.info("No admissions data loaded; running an initial refresh")
        await asyncio.to_thread(ingestion.run_refresh, "startup")

    task = asyncio.create_task(_refresh_scheduler())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Admissions & Finance AI Agent", version="3.0.0", lifespan=lifespan)
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
