from typing import Any

from fastapi import APIRouter

from app.db.client import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, Any]:
    try:
        db = get_db()
        db.version()
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return {"status": "not_ready", "database": str(e)}
