from sqlalchemy import select

from app.database.models.standings import Standings
from app.database.repositories.base import BaseRepository


class StandingsRepository(BaseRepository[Standings]):
    def __init__(self, session):
        super().__init__(session, Standings)

    async def get_for_team(
        self, organization_id: str, tournament_id: str,
        team_id: str, bracket_id: str | None = None
    ) -> Standings | None:
        q = (
            select(Standings)
            .where(Standings.organization_id == organization_id)
            .where(Standings.tournament_id == tournament_id)
            .where(Standings.team_id == team_id)
        )
        if bracket_id:
            q = q.where(Standings.bracket_id == bracket_id)
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def get_ranked(
        self, organization_id: str, tournament_id: str,
        bracket_id: str | None = None, limit: int = 100
    ) -> list[Standings]:
        q = (
            select(Standings)
            .where(Standings.organization_id == organization_id)
            .where(Standings.tournament_id == tournament_id)
        )
        if bracket_id:
            q = q.where(Standings.bracket_id == bracket_id)
        q = q.order_by(Standings.rank.asc().nulls_last(), Standings.points.desc()).limit(limit)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def upsert(
        self, organization_id: str, tournament_id: str, team_id: str,
        bracket_id: str | None = None, **kwargs
    ) -> Standings:
        existing = await self.get_for_team(organization_id, tournament_id, team_id, bracket_id)
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            await self.session.flush()
            return existing
        s = Standings(
            organization_id=organization_id,
            tournament_id=tournament_id,
            team_id=team_id,
            bracket_id=bracket_id,
            **kwargs,
        )
        self.session.add(s)
        await self.session.flush()
        return s
