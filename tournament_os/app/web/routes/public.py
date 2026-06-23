"""
Public routes — tournament listings, individual tournament pages.
No auth required.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.database.repositories.tournament import TournamentRepository
from app.database.models.tournament import TournamentStatus

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/tournaments")
async def list_public_tournaments(
    limit: int = 20, offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    repo = TournamentRepository(session)
    tournaments = await repo.list_public(limit=limit, offset=offset)
    return {
        "tournaments": [
            {
                "id": t.id,
                "name": t.name,
                "slug": t.slug,
                "game": t.game,
                "format": t.format.value,
                "status": t.status.value,
                "prize_pool": t.prize_pool,
                "max_teams": t.max_teams,
                "region": t.region,
                "registration_open_at": str(t.registration_open_at or ""),
                "match_start_at": str(t.match_start_at or ""),
            }
            for t in tournaments
        ],
        "total": len(tournaments),
        "limit": limit,
        "offset": offset,
    }


@router.get("/tournaments/{tournament_id}")
async def get_public_tournament(
    tournament_id: str,
    organization_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = TournamentRepository(session)
    t = await repo.get_by_id(tournament_id, organization_id)
    if not t or t.visibility != "public":
        raise HTTPException(status_code=404, detail="Tournament not found")

    return {
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "game": t.game,
        "format": t.format.value,
        "status": t.status.value,
        "description": t.description,
        "rules": t.rules,
        "prize_pool": t.prize_pool,
        "max_teams": t.max_teams,
        "region": t.region,
        "platform": t.platform,
        "registration_open_at": str(t.registration_open_at or ""),
        "registration_close_at": str(t.registration_close_at or ""),
        "checkin_open_at": str(t.checkin_open_at or ""),
        "match_start_at": str(t.match_start_at or ""),
    }


@router.get("/tournaments/{tournament_id}/standings")
async def get_public_standings(
    tournament_id: str, organization_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    from app.ai.tools.db_tools import AIDBTools
    tools = AIDBTools(session, organization_id, tournament_id)
    standings = await tools.get_standings(limit=limit)
    return {"standings": standings}
