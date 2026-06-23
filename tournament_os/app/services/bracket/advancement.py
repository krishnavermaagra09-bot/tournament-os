"""
Bracket advancement service — promotes winners/losers to next match.

BracketAdvancement  — low-level: advance a single winner to next match slot
BracketAdvancementService — high-level: generate full next rounds (alias used by autonomous engine)
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.match import Match, MatchStatus
from app.database.repositories.match import MatchRepository
from app.services.match.scheduler import MatchScheduler

logger = logging.getLogger(__name__)


class BracketAdvancement:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.match_repo = MatchRepository(session)
        self.scheduler = MatchScheduler(session)

    async def advance_winner(
        self,
        completed_match: Match,
        organization_id: str,
        tournament_id: str,
    ) -> None:
        """
        After a match completes, find the next match in the bracket
        and slot the winner in. For single elimination, bracket_data
        tracks match-to-next-match mapping.
        """
        if not completed_match.winner_id:
            return
        if not completed_match.bracket_id:
            return

        # Find next match for winner based on bracket structure
        next_match_number = (completed_match.match_number + 1) // 2
        next_round = completed_match.round + 1

        from sqlalchemy import select
        from app.database.models.match import Match as MatchModel
        q = (
            select(MatchModel)
            .where(MatchModel.organization_id == organization_id)
            .where(MatchModel.tournament_id == tournament_id)
            .where(MatchModel.bracket_id == completed_match.bracket_id)
            .where(MatchModel.round == next_round)
            .where(MatchModel.match_number == next_match_number)
        )
        result = await self.session.execute(q)
        next_match = result.scalar_one_or_none()

        if not next_match:
            logger.info("No next match found for winner — tournament may be complete")
            return

        # Slot winner into team1 or team2 position
        if completed_match.match_number % 2 == 1:
            next_match.team1_id = completed_match.winner_id
        else:
            next_match.team2_id = completed_match.winner_id

        await self.session.flush()
        logger.info(
            "Advanced winner %s to round %d match %d",
            completed_match.winner_id, next_round, next_match_number
        )

    async def generate_next_swiss_round(
        self,
        organization_id: str,
        tournament_id: str,
        bracket_id: str,
        current_round: int,
    ) -> list[Match]:
        """
        Swiss pairing for round N+1: pair teams with same win count,
        avoiding rematches where possible.
        """
        from sqlalchemy import select
        from app.database.models.standings import Standings
        from app.database.models.match import Match as MatchModel

        standings_q = (
            select(Standings)
            .where(Standings.organization_id == organization_id)
            .where(Standings.tournament_id == tournament_id)
            .order_by(Standings.wins.desc(), Standings.points.desc())
        )
        result = await self.session.execute(standings_q)
        standings = list(result.scalars().all())

        # Get all previous pairings to avoid rematches
        prev_q = (
            select(MatchModel)
            .where(MatchModel.bracket_id == bracket_id)
            .where(MatchModel.status == MatchStatus.COMPLETED)
        )
        prev_result = await self.session.execute(prev_q)
        prev_matches = list(prev_result.scalars().all())
        played_pairs: set[frozenset] = {
            frozenset([m.team1_id, m.team2_id]) for m in prev_matches if m.team1_id and m.team2_id
        }

        team_ids = [s.team_id for s in standings]
        pairings: list[tuple[str | None, str | None]] = []
        used: set[str] = set()

        for i, t1 in enumerate(team_ids):
            if t1 in used:
                continue
            for t2 in team_ids[i + 1:]:
                if t2 in used:
                    continue
                if frozenset([t1, t2]) not in played_pairs:
                    pairings.append((t1, t2))
                    used.add(t1)
                    used.add(t2)
                    break

        return await self.scheduler.schedule_round(
            organization_id, tournament_id, bracket_id,
            round=current_round + 1, pairings=pairings,
        )

    async def generate_next_round(
        self,
        organization_id: str,
        tournament_id: str,
        bracket_id: str,
    ) -> list[Match]:
        """
        Generate the next round of matches for elimination formats.

        Strategy:
          1. Find all completed matches in the bracket.
          2. Identify the last completed round.
          3. Look for pre-existing next-round matches (SE/DE bracket generator
             creates all rounds upfront). If found and both teams are filled in,
             return them; if missing teams, fill them from the winners list.
          4. If no pre-existing matches, create new ones from winners (on-demand
             bracket formats like Group Stage).
          5. Raise ValueError("Tournament complete") when only one team remains.
        """
        from sqlalchemy import select
        from app.database.models.match import Match as MatchModel

        q = select(MatchModel).where(
            MatchModel.organization_id == organization_id,
            MatchModel.tournament_id == tournament_id,
            MatchModel.bracket_id == bracket_id,
        )
        all_matches = list((await self.session.execute(q)).scalars().all())

        if not all_matches:
            raise ValueError("No matches in bracket")

        completed = [m for m in all_matches if m.status == MatchStatus.COMPLETED]
        if not completed:
            raise ValueError("No completed matches to advance from")

        last_round = max(m.round for m in completed if m.round is not None)
        last_round_matches = [m for m in completed if m.round == last_round]

        winners = [m.winner_id for m in last_round_matches if m.winner_id]

        if not winners:
            raise ValueError("No winners in the last round")

        if len(winners) == 1:
            raise ValueError("Tournament complete — only one team remains")

        next_round = last_round + 1

        # Look for pre-existing next-round matches (SE/DE creates them upfront)
        existing_next = [m for m in all_matches if m.round == next_round]

        if existing_next:
            # Fill in any team slots that are still None
            ready = [m for m in existing_next if m.team1_id and m.team2_id]
            if ready:
                logger.info(
                    "generate_next_round: %d pre-existing round %d matches already have teams",
                    len(ready), next_round,
                )
                return ready

            # Slot winners into empty slots using same odd/even logic as advance_winner
            for match in last_round_matches:
                if not match.winner_id:
                    continue
                next_match_number = (match.match_number + 1) // 2
                target = next((m for m in existing_next if m.match_number == next_match_number), None)
                if target:
                    if match.match_number % 2 == 1:
                        target.team1_id = match.winner_id
                    else:
                        target.team2_id = match.winner_id

            await self.session.flush()
            filled = [m for m in existing_next if m.team1_id and m.team2_id]
            logger.info(
                "generate_next_round: filled %d/%d round %d matches",
                len(filled), len(existing_next), next_round,
            )
            return filled

        # No pre-existing matches — create on-demand
        pairings: list[tuple[str | None, str | None]] = [
            (winners[i], winners[i + 1] if i + 1 < len(winners) else None)
            for i in range(0, len(winners), 2)
        ]
        new_matches = await self.scheduler.schedule_round(
            organization_id, tournament_id, bracket_id,
            round=next_round, pairings=pairings,
        )
        logger.info(
            "generate_next_round: created %d new round %d matches",
            len(new_matches), next_round,
        )
        return new_matches

    async def generate_swiss_round(
        self,
        organization_id: str,
        tournament_id: str,
        bracket_id: str,
        target_round: int,
    ) -> list[Match]:
        """
        Generate Swiss round `target_round`.
        Wraps generate_next_swiss_round which takes current_round = target_round - 1.
        """
        return await self.generate_next_swiss_round(
            organization_id, tournament_id, bracket_id,
            current_round=target_round - 1,
        )


# Alias used by the autonomous engine — same implementation
BracketAdvancementService = BracketAdvancement
