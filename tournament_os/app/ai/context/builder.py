"""
AI context builder — assembles the scoped context for every query.
Context is ALWAYS bound to organization_id + guild_id + tournament_id.
No cross-tournament or cross-org data ever enters the context.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.tournament import TournamentRepository
from app.database.repositories.standings import StandingsRepository

logger = logging.getLogger(__name__)


class ContextBuilder:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.tournament_repo = TournamentRepository(session)
        self.standings_repo = StandingsRepository(session)

    async def build(
        self,
        organization_id: str,
        guild_id: str,
        tournament_id: str | None,
        user_discord_id: str,
    ) -> dict:
        """
        Returns a context dict passed to the AI agent.
        All data is scoped to org + guild + tournament.
        """
        ctx: dict = {
            "organization_id": organization_id,
            "guild_id": guild_id,
            "tournament_id": tournament_id,
            "user_discord_id": user_discord_id,
        }

        if tournament_id:
            tournament = await self.tournament_repo.get_by_id(tournament_id, organization_id)
            if tournament:
                ctx["tournament"] = {
                    "id": tournament.id,
                    "name": tournament.name,
                    "game": tournament.game,
                    "format": tournament.format.value,
                    "status": tournament.status.value,
                    "registration_open_at": str(tournament.registration_open_at or ""),
                    "registration_close_at": str(tournament.registration_close_at or ""),
                    "checkin_open_at": str(tournament.checkin_open_at or ""),
                    "checkin_close_at": str(tournament.checkin_close_at or ""),
                    "match_start_at": str(tournament.match_start_at or ""),
                    "prize_pool": tournament.prize_pool or "",
                    "rules": tournament.rules or "",
                    "max_teams": tournament.max_teams,
                    "allow_duplicates": tournament.allow_duplicates,
                }

        return ctx
