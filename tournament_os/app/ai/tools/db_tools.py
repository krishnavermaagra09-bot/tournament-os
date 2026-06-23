"""
AI live DB query tools — read-only, always scoped to org + guild + tournament.
These are the functions the AI agent calls to fetch live data.
Every function enforces the isolation filter — no raw queries that omit it.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models.registration import Registration, RegistrationStatus
from app.database.models.match import Match, MatchStatus
from app.database.models.standings import Standings
from app.database.models.team import Team, TeamMember
from app.database.models.user import User

logger = logging.getLogger(__name__)


class AIDBTools:
    def __init__(self, session: AsyncSession, organization_id: str, tournament_id: str | None):
        self.session = session
        self.org_id = organization_id
        self.t_id = tournament_id

    def _require_tournament(self) -> str:
        if not self.t_id:
            raise ValueError("A tournament must be selected to query tournament data.")
        return self.t_id

    async def get_my_registration(self, discord_user_id: str) -> dict | None:
        t_id = self._require_tournament()
        q = (
            select(Registration)
            .join(User, Registration.submitted_by == User.id)
            .where(Registration.organization_id == self.org_id)
            .where(Registration.tournament_id == t_id)
            .where(User.discord_user_id == discord_user_id)
            .where(Registration.deleted_at.is_(None))
        )
        result = await self.session.execute(q)
        reg = result.scalar_one_or_none()
        if not reg:
            return None
        return {
            "id": reg.id,
            "status": reg.status.value,
            "submitted_at": str(reg.created_at),
            "flags": len(reg.duplicate_flags or []),
            "rejection_reason": reg.rejection_reason,
        }

    async def get_my_matches(self, discord_user_id: str) -> list[dict]:
        t_id = self._require_tournament()
        # Find user's team
        q = (
            select(TeamMember)
            .join(User, TeamMember.user_id == User.id)
            .where(TeamMember.tournament_id == t_id)
            .where(User.discord_user_id == discord_user_id)
            .where(TeamMember.is_active.is_(True))
        )
        result = await self.session.execute(q)
        member = result.scalar_one_or_none()
        if not member:
            return []

        q2 = (
            select(Match)
            .where(Match.organization_id == self.org_id)
            .where(Match.tournament_id == t_id)
            .where((Match.team1_id == member.team_id) | (Match.team2_id == member.team_id))
            .where(Match.deleted_at.is_(None))
            .order_by(Match.scheduled_at.asc())
        )
        result2 = await self.session.execute(q2)
        matches = result2.scalars().all()
        return [
            {
                "id": m.id,
                "round": m.round,
                "status": m.status.value,
                "scheduled_at": str(m.scheduled_at or "TBD"),
                "opponent_id": m.team2_id if m.team1_id == member.team_id else m.team1_id,
            }
            for m in matches
        ]

    async def get_standings(self, limit: int = 20) -> list[dict]:
        t_id = self._require_tournament()
        q = (
            select(Standings, Team)
            .join(Team, Standings.team_id == Team.id)
            .where(Standings.organization_id == self.org_id)
            .where(Standings.tournament_id == t_id)
            .order_by(Standings.rank.asc().nulls_last(), Standings.points.desc())
            .limit(limit)
        )
        result = await self.session.execute(q)
        rows = result.all()
        return [
            {
                "rank": s.rank,
                "team_name": t.name,
                "points": float(s.points),
                "wins": s.wins,
                "losses": s.losses,
                "matches_played": s.matches_played,
            }
            for s, t in rows
        ]

    async def get_live_matches(self) -> list[dict]:
        t_id = self._require_tournament()
        q = (
            select(Match)
            .where(Match.organization_id == self.org_id)
            .where(Match.tournament_id == t_id)
            .where(Match.status == MatchStatus.LIVE)
        )
        result = await self.session.execute(q)
        matches = result.scalars().all()
        return [{"id": m.id, "round": m.round, "match_number": m.match_number} for m in matches]

    async def get_tournament_info(self) -> dict:
        t_id = self._require_tournament()
        from app.database.repositories.tournament import TournamentRepository
        repo = TournamentRepository(self.session)
        t = await repo.get_by_id(t_id, self.org_id)
        if not t:
            return {}
        return {
            "name": t.name,
            "game": t.game,
            "status": t.status.value,
            "format": t.format.value,
            "prize_pool": t.prize_pool or "N/A",
            "registration_open_at": str(t.registration_open_at or ""),
            "registration_close_at": str(t.registration_close_at or ""),
            "match_start_at": str(t.match_start_at or ""),
            "rules": t.rules or "No rules specified.",
            "max_teams": t.max_teams,
        }
