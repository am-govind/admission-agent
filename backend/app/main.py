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

import time

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, auth, chat, conversations
from .core import migrate, security
from .core.config import settings
from .core.logs import bind_request, setup_logging
from .data import availability, ingestion
from .data.schema import TABLE_RD26

log = logging.getLogger(__name__)

# Polled by monitors, so logging it would drown everything else.
_QUIET_PATHS = {"/health"}


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
    setup_logging()
    log.info("Starting %s in %s mode on %s:%s", app.title, settings.app_env,
             settings.api_host, settings.api_port)
    log.info("Analytics DB %s, app DB %s, data source %s",
             settings.duckdb_file, settings.appdb_file, settings.data_source)
    if settings.jwt_secret == "change-me":
        log.warning("JWT_SECRET is still the default value; set it in backend/.env")

    migrate.migrate_app_state()
    security.bootstrap_admin()

    if settings.refresh_on_startup_if_empty and not availability.is_available(TABLE_RD26):
        log.info("No admissions data loaded; running an initial refresh")
        await asyncio.to_thread(ingestion.run_refresh, "startup")
    else:
        log.info("Data status: %s", availability.row_counts())

    task = asyncio.create_task(_refresh_scheduler())
    log.info("Refresh scheduler armed for %s %s (polling every %ss)",
             settings.refresh_at, settings.refresh_tz, settings.refresh_poll_seconds)
    try:
        yield
    finally:
        log.info("Shutting down; stopping the refresh scheduler")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="Admissions & Finance AI Agent", version="3.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Assign a request id, then log the outcome and how long it took.

        The id is echoed as `X-Request-Id` so a slow or failed answer reported by a user
        can be found in the log without guessing from timestamps.
        """
        rid = bind_request(request.headers.get("X-Request-Id"))
        started = time.perf_counter()
        quiet = request.url.path in _QUIET_PATHS
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            log.exception("%s %s failed after %.0fms", request.method,
                          request.url.path, elapsed)
            raise
        elapsed = (time.perf_counter() - started) * 1000
        if not quiet:
            level = logging.WARNING if response.status_code >= 400 else logging.INFO
            log.log(level, "%s %s -> %s in %.0fms", request.method, request.url.path,
                    response.status_code, elapsed)
        response.headers["X-Request-Id"] = rid
        return response

    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(admin.router)
    return app


app = create_app()
