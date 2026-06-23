"""
Check-in service — handles tournament-level and match-level check-ins.
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.checkin import CheckIn
from app.database.models.tournament import Tournament
from app.database.repositories.audit import AuditRepository
from app.database.repositories.team import TeamRepository

logger = logging.getLogger(__name__)


class CheckInService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit = AuditRepository(session)
        self.team_repo = TeamRepository(session)

    async def checkin_team(
        self,
        tournament: Tournament,
        team_id: str,
        user_id: str | None,
        method: str = "button",
        match_id: str | None = None,
    ) -> CheckIn:
        now = datetime.now(timezone.utc)

        # Validate check-in window for tournament-level check-in
        if match_id is None:
            if tournament.checkin_open_at and now < tournament.checkin_open_at:
                raise ValueError("Check-in window has not opened yet.")
            if tournament.checkin_close_at and now > tournament.checkin_close_at:
                raise ValueError("Check-in window has closed.")

        checkin = CheckIn(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            match_id=match_id,
            team_id=team_id,
            user_id=user_id,
            checked_in_at=now,
            method=method,
        )
        self.session.add(checkin)

        # Update team checkin_status
        team = await self.team_repo.get_by_id(team_id, tournament.organization_id, tournament.id)
        if team:
            team.checkin_status = "checked_in"

        await self.session.flush()

        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="checkin.completed",
            actor_id=user_id,
            target_type="team",
            target_id=team_id,
            payload={"method": method, "match_id": match_id},
        )

        logger.info("Team %s checked in for tournament %s", team_id, tournament.id)
        return checkin

    async def is_checked_in(
        self, tournament_id: str, organization_id: str, team_id: str
    ) -> bool:
        from sqlalchemy import select
        q = (
            select(CheckIn)
            .where(CheckIn.tournament_id == tournament_id)
            .where(CheckIn.team_id == team_id)
            .where(CheckIn.match_id.is_(None))
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none() is not None
