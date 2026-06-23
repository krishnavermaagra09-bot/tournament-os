"""
Standings calculator — updates standings after match completion.
Handles SE/DE (wins/losses), Round Robin (points), Swiss, League, Battle Royale.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.standings import StandingsRepository
from app.database.repositories.match import MatchRepository

logger = logging.getLogger(__name__)


class StandingsCalculator:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = StandingsRepository(session)
        self.match_repo = MatchRepository(session)

    async def update_after_match(
        self,
        organization_id: str,
        tournament_id: str,
        match_id: str,
        winner_id: str | None = None,
        loser_id: str | None = None,
        draw: bool = False,
    ) -> None:
        match = await self.match_repo.get_by_id(match_id, organization_id, tournament_id)
        if not match:
            return

        if draw:
            for team_id in [match.team1_id, match.team2_id]:
                if team_id:
                    s = await self.repo.upsert(
                        organization_id, tournament_id, team_id, match.bracket_id
                    )
                    s.draws += 1
                    s.matches_played += 1
                    s.points += 1
        else:
            if winner_id:
                s = await self.repo.upsert(
                    organization_id, tournament_id, winner_id, match.bracket_id
                )
                s.wins += 1
                s.matches_played += 1
                s.points += 3

            if loser_id:
                s = await self.repo.upsert(
                    organization_id, tournament_id, loser_id, match.bracket_id
                )
                s.losses += 1
                s.matches_played += 1

        await self.session.flush()
        await self._recalculate_ranks(organization_id, tournament_id, match.bracket_id)

    async def _recalculate_ranks(
        self, organization_id: str, tournament_id: str, bracket_id: str | None
    ) -> None:
        """Re-rank all teams by points desc, then wins desc."""
        standings = await self.repo.get_ranked(organization_id, tournament_id, bracket_id)
        for i, s in enumerate(standings, start=1):
            s.rank = i
        await self.session.flush()

    async def update_br_standings(
        self, organization_id: str, tournament_id: str
    ) -> None:
        """
        Aggregate Battle Royale results across all completed lobbies
        and update standings with cumulative points.
        """
        from sqlalchemy import select, func, text
        from app.database.models.match import BattleRoyaleResult

        q = (
            select(
                BattleRoyaleResult.team_id,
                func.sum(
                    BattleRoyaleResult.placement_points +
                    BattleRoyaleResult.kill_points +
                    BattleRoyaleResult.bonus_points -
                    BattleRoyaleResult.penalty_points
                ).label("total"),
            )
            .where(BattleRoyaleResult.organization_id == organization_id)
            .where(BattleRoyaleResult.tournament_id == tournament_id)
            .group_by(BattleRoyaleResult.team_id)
            .order_by(text("total DESC"))
        )
        result = await self.session.execute(q)
        rows = result.all()

        for rank, row in enumerate(rows, start=1):
            s = await self.repo.upsert(
                organization_id, tournament_id, row.team_id,
                bracket_id=None,
                points=float(row.total),
                rank=rank,
            )

        await self.session.flush()
