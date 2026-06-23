"""
Analytics aggregator — computes dashboard metrics from DB.
All queries filtered by organization_id + tournament_id.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from app.database.models.registration import Registration, RegistrationStatus
from app.database.models.team import Team
from app.database.models.match import Match, MatchStatus
from app.database.models.dispute import Dispute, DisputeStatus
from app.database.models.checkin import CheckIn

logger = logging.getLogger(__name__)


class AnalyticsAggregator:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def tournament_summary(
        self, organization_id: str, tournament_id: str
    ) -> dict:
        # Registrations
        reg_q = (
            select(
                func.count(Registration.id).label("total"),
                func.sum(case((Registration.status == RegistrationStatus.MANUALLY_APPROVED, 1), else_=0)).label("approved"),
                func.sum(case((Registration.status == RegistrationStatus.AUTO_APPROVED, 1), else_=0)).label("auto_approved"),
                func.sum(case((Registration.status == RegistrationStatus.REJECTED, 1), else_=0)).label("rejected"),
                func.sum(case((Registration.status == RegistrationStatus.PENDING, 1), else_=0)).label("pending"),
                func.sum(case((Registration.status == RegistrationStatus.FLAGGED, 1), else_=0)).label("flagged"),
            )
            .where(Registration.organization_id == organization_id)
            .where(Registration.tournament_id == tournament_id)
            .where(Registration.deleted_at.is_(None))
        )
        reg_result = await self.session.execute(reg_q)
        reg = reg_result.one()

        # Teams
        team_q = (
            select(func.count(Team.id).label("total_teams"))
            .where(Team.organization_id == organization_id)
            .where(Team.tournament_id == tournament_id)
            .where(Team.deleted_at.is_(None))
        )
        team_result = await self.session.execute(team_q)
        team_count = team_result.scalar_one() or 0

        # Check-ins
        checkin_q = (
            select(func.count(CheckIn.id).label("checked_in"))
            .where(CheckIn.organization_id == organization_id)
            .where(CheckIn.tournament_id == tournament_id)
            .where(CheckIn.match_id.is_(None))
        )
        checkin_result = await self.session.execute(checkin_q)
        checked_in = checkin_result.scalar_one() or 0

        # Matches
        match_q = (
            select(
                func.count(Match.id).label("total"),
                func.sum(case((Match.status == MatchStatus.COMPLETED, 1), else_=0)).label("completed"),
                func.sum(case((Match.status == MatchStatus.LIVE, 1), else_=0)).label("live"),
            )
            .where(Match.organization_id == organization_id)
            .where(Match.tournament_id == tournament_id)
            .where(Match.deleted_at.is_(None))
        )
        match_result = await self.session.execute(match_q)
        matches = match_result.one()

        # Disputes
        dispute_q = (
            select(func.count(Dispute.id).label("total"))
            .where(Dispute.organization_id == organization_id)
            .where(Dispute.tournament_id == tournament_id)
            .where(Dispute.deleted_at.is_(None))
        )
        dispute_result = await self.session.execute(dispute_q)
        dispute_count = dispute_result.scalar_one() or 0

        total_reg = reg.total or 0
        approved = (reg.approved or 0) + (reg.auto_approved or 0)

        return {
            "registrations": {
                "total": total_reg,
                "approved": approved,
                "rejected": reg.rejected or 0,
                "pending": reg.pending or 0,
                "flagged": reg.flagged or 0,
                "approval_rate": round(approved / total_reg * 100, 1) if total_reg else 0,
            },
            "teams": {
                "total": team_count,
                "checked_in": checked_in,
                "checkin_rate": round(checked_in / team_count * 100, 1) if team_count else 0,
            },
            "matches": {
                "total": matches.total or 0,
                "completed": matches.completed or 0,
                "live": matches.live or 0,
            },
            "disputes": {
                "total": dispute_count,
            },
        }
