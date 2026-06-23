from sqlalchemy import select

from app.database.models.team import Team, TeamMember
from app.database.models.user import User
from app.database.repositories.base import BaseRepository


class TeamRepository(BaseRepository[Team]):
    def __init__(self, session):
        super().__init__(session, Team)

    async def get_by_name(
        self, organization_id: str, tournament_id: str, name: str
    ) -> Team | None:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Team.name == name)
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def get_by_captain(
        self, organization_id: str, tournament_id: str, discord_user_id: str
    ) -> Team | None:
        """
        Find the team whose captain matches the given Discord user ID.
        Joins through the User table because Team.captain_id is a FK to users.id
        (an internal UUID), not a Discord snowflake.
        """
        q = (
            self._base_query(organization_id, tournament_id)
            .join(User, Team.captain_id == User.id)
            .where(User.discord_user_id == discord_user_id)
            .where(User.deleted_at.is_(None))
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def list_checked_in(
        self, organization_id: str, tournament_id: str
    ) -> list[Team]:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Team.checkin_status == "checked_in")
            .where(Team.is_reserve.is_(False))
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_reserves(
        self, organization_id: str, tournament_id: str
    ) -> list[Team]:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Team.is_reserve.is_(True))
            .order_by(Team.created_at.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def add_member(
        self, organization_id: str, tournament_id: str, team_id: str,
        user_id: str, role: str = "member"
    ) -> TeamMember:
        from datetime import datetime, timezone
        member = TeamMember(
            organization_id=organization_id,
            tournament_id=tournament_id,
            team_id=team_id,
            user_id=user_id,
            role=role,
            joined_at=datetime.now(timezone.utc),
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_member(
        self, team_id: str, user_id: str, tournament_id: str
    ) -> TeamMember | None:
        q = (
            select(TeamMember)
            .where(TeamMember.team_id == team_id)
            .where(TeamMember.user_id == user_id)
            .where(TeamMember.tournament_id == tournament_id)
            .where(TeamMember.is_active.is_(True))
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()
