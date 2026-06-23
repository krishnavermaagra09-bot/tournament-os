"""
Health check endpoints — used by Railway for service health monitoring.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database.session import get_session

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    """Lightweight liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)):
    """Readiness probe — verifies DB connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"Database not ready: {e}")
