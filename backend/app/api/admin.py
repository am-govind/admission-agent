"""Admin/ops routes — health, data refresh, freshness metadata."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from ..agent.skills import list_skills
from ..agent.tools import REGISTRY
from ..core import appdb
from ..core.config import settings
from ..core.security import current_user
from ..data import availability, ingestion

router = APIRouter(tags=["admin"])


@router.get("/health")
def health() -> dict:
    """Unauthenticated liveness probe; deliberately reveals nothing about the data."""
    return {"status": "ok"}


@router.get("/meta")
def meta(user: str = Depends(current_user)) -> dict:
    """Data freshness, table availability and what the agent can do."""
    return {
        **availability.summary(),
        "dataSource": settings.data_source,
        "refreshAt": f"{settings.refresh_at} {settings.refresh_tz}",
        "refreshDue": availability.refresh_due(),
        "skills": [{"id": s.skill_id, "name": s.name, "description": s.description,
                    "tools": list(s.tool_names)} for s in list_skills()],
        "toolCount": len(REGISTRY),
    }


@router.get("/refresh/history")
def refresh_history(limit: int = 10, user: str = Depends(current_user)) -> dict:
    rows = appdb.query(
        "SELECT run_id, trigger, source, started_at, finished_at, status, row_counts, "
        "error FROM refresh_runs ORDER BY started_at DESC LIMIT ?",
        [max(1, min(limit, 100))])
    keys = ("runId", "trigger", "source", "startedAt", "finishedAt", "status",
            "rowCounts", "error")
    return {"runs": [dict(zip(keys, row)) for row in rows]}


@router.post("/refresh")
async def refresh(user: str = Depends(current_user)) -> dict:
    """Trigger a refresh now. Runs off the event loop; never raises on failure."""
    return await asyncio.to_thread(ingestion.run_refresh, "manual")
