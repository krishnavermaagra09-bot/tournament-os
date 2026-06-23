"""
Match scheduling service — creates matches for a given bracket.
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.match import Match, MatchStatus
from app.database.repositories.match import MatchRepository

logger = logging.getLogger(__name__)


class MatchScheduler:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MatchRepository(session)

    async def create_match(
        self,
        organization_id: str,
        tournament_id: str,
        bracket_id: str | None,
        round: int,
        match_number: int,
        team1_id: str | None = None,
        team2_id: str | None = None,
        scheduled_at: datetime | None = None,
        lobby_number: int | None = None,
    ) -> Match:
        match = Match(
            organization_id=organization_id,
            tournament_id=tournament_id,
            bracket_id=bracket_id,
            round=round,
            match_number=match_number,
            team1_id=team1_id,
            team2_id=team2_id,
            scheduled_at=scheduled_at,
            lobby_number=lobby_number,
            status=MatchStatus.SCHEDULED,
        )
        self.session.add(match)
        await self.session.flush()
        await self.session.refresh(match)
        logger.info("Match created: %s r%d m%d", match.id, round, match_number)
        return match

    async def schedule_round(
        self,
        organization_id: str,
        tournament_id: str,
        bracket_id: str,
        round: int,
        pairings: list[tuple[str | None, str | None]],
        scheduled_at: datetime | None = None,
    ) -> list[Match]:
        """Create all matches for a round given pairings [(team1_id, team2_id)]."""
        matches: list[Match] = []
        for i, (t1, t2) in enumerate(pairings, start=1):
            m = await self.create_match(
                organization_id=organization_id,
                tournament_id=tournament_id,
                bracket_id=bracket_id,
                round=round,
                match_number=i,
                team1_id=t1,
                team2_id=t2,
                scheduled_at=scheduled_at,
            )
            matches.append(m)
        return matches
