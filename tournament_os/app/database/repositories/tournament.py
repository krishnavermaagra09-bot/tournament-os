from sqlalchemy import select

from app.database.models.tournament import Tournament, TournamentStatus
from app.database.repositories.base import BaseRepository


class TournamentRepository(BaseRepository[Tournament]):
    def __init__(self, session):
        super().__init__(session, Tournament)

    async def get_by_slug(self, organization_id: str, slug: str) -> Tournament | None:
        q = (
            select(Tournament)
            .where(Tournament.organization_id == organization_id)
            .where(Tournament.slug == slug)
            .where(Tournament.deleted_at.is_(None))
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def list_by_status(
        self, organization_id: str, status: TournamentStatus,
        limit: int = 50, offset: int = 0
    ) -> list[Tournament]:
        q = (
            select(Tournament)
            .where(Tournament.organization_id == organization_id)
            .where(Tournament.status == status)
            .where(Tournament.deleted_at.is_(None))
            .order_by(Tournament.created_at.desc())
            .limit(limit).offset(offset)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_public(self, limit: int = 50, offset: int = 0) -> list[Tournament]:
        public_statuses = [
            TournamentStatus.SCHEDULED,
            TournamentStatus.REGISTRATION_OPEN,
            TournamentStatus.REGISTRATION_CLOSED,
            TournamentStatus.CHECKIN_OPEN,
            TournamentStatus.CHECKIN_CLOSED,
            TournamentStatus.LIVE,
            TournamentStatus.COMPLETED,
        ]
        q = (
            select(Tournament)
            .where(Tournament.status.in_(public_statuses))
            .where(Tournament.visibility == "public")
            .where(Tournament.deleted_at.is_(None))
            .order_by(Tournament.match_start_at.asc())
            .limit(limit).offset(offset)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def update_status(
        self, tournament_id: str, organization_id: str, new_status: TournamentStatus
    ) -> Tournament | None:
        t = await self.get_by_id(tournament_id, organization_id)
        if not t:
            return None
        t.status = new_status
        await self.session.flush()
        return t

    async def list_by_guild(self, discord_guild_id: str, limit: int = 50) -> list[Tournament]:
        from app.database.models.guild import Guild
        q = (
            select(Tournament)
            .join(Guild, Tournament.guild_id == Guild.id)
            .where(Guild.discord_guild_id == discord_guild_id)
            .where(Tournament.deleted_at.is_(None))
            .order_by(Tournament.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())
