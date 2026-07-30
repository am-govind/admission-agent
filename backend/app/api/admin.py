"""Admin/ops routes — health, data refresh, metadata."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core.database import execute
from ..core.security import current_user
from ..data import ingestion

router = APIRouter(tags=["admin"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/meta")
def meta(user: str = Depends(current_user)) -> dict:
    rows = execute("SELECT key, value FROM meta")
    return {k: v for k, v in rows}


@router.post("/refresh")
def refresh(user: str = Depends(current_user)) -> dict:
    counts = ingestion.refresh()
    return {"refreshed": True, "counts": counts}
