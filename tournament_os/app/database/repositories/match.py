from sqlalchemy import select

from app.database.models.match import Match, MatchStatus, BattleRoyaleResult
from app.database.repositories.base import BaseRepository


class MatchRepository(BaseRepository[Match]):
    def __init__(self, session):
        super().__init__(session, Match)

    async def list_by_team(
        self, organization_id: str, tournament_id: str, team_id: str
    ) -> list[Match]:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(
                (Match.team1_id == team_id) | (Match.team2_id == team_id)
            )
            .order_by(Match.scheduled_at.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_by_status(
        self, organization_id: str, tournament_id: str, status: MatchStatus
    ) -> list[Match]:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Match.status == status)
            .order_by(Match.scheduled_at.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_by_bracket(
        self, organization_id: str, tournament_id: str, bracket_id: str
    ) -> list[Match]:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Match.bracket_id == bracket_id)
            .order_by(Match.round.asc(), Match.match_number.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def update_status(
        self, match_id: str, organization_id: str, tournament_id: str,
        status: MatchStatus
    ) -> Match | None:
        match = await self.get_by_id(match_id, organization_id, tournament_id)
        if not match:
            return None
        match.status = status
        await self.session.flush()
        return match

    async def submit_score(
        self, match_id: str, organization_id: str, tournament_id: str,
        score_team1: dict, score_team2: dict,
        winner_id: str | None = None, loser_id: str | None = None,
        override_by: str | None = None, override_reason: str | None = None
    ) -> Match | None:
        match = await self.get_by_id(match_id, organization_id, tournament_id)
        if not match:
            return None
        match.score_team1 = score_team1
        match.score_team2 = score_team2
        if winner_id:
            match.winner_id = winner_id
        if loser_id:
            match.loser_id = loser_id
        if override_by:
            match.score_overridden_by = override_by
            match.score_override_reason = override_reason
        match.status = MatchStatus.COMPLETED
        await self.session.flush()
        return match

    async def save_br_result(self, result: BattleRoyaleResult) -> BattleRoyaleResult:
        self.session.add(result)
        await self.session.flush()
        return result

    async def get_br_results(
        self, organization_id: str, tournament_id: str, match_id: str
    ) -> list[BattleRoyaleResult]:
        q = (
            select(BattleRoyaleResult)
            .where(BattleRoyaleResult.organization_id == organization_id)
            .where(BattleRoyaleResult.tournament_id == tournament_id)
            .where(BattleRoyaleResult.match_id == match_id)
            .order_by(BattleRoyaleResult.lobby_number.asc(), BattleRoyaleResult.placement.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())
