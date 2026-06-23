"""
No-show handler — runs at check-in close to auto-remove teams that didn't check in.
Promotes reserve teams if available and auto-removal is configured.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.team import Team
from app.database.repositories.audit import AuditRepository
from app.database.repositories.team import TeamRepository
from app.database.repositories.tournament import TournamentRepository

logger = logging.getLogger(__name__)


class NoShowHandler:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.team_repo = TeamRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.audit = AuditRepository(session)

    async def process_noshows(
        self, organization_id: str, tournament_id: str
    ) -> dict:
        tournament = await self.tournament_repo.get_by_id(tournament_id, organization_id)
        if not tournament:
            raise ValueError(f"Tournament {tournament_id} not found")

        policy = tournament.auto_removal_policy
        auto_remove = policy.get("enabled", False)

        teams = await self.team_repo.list_all(organization_id, tournament_id)
        reserves = await self.team_repo.list_reserves(organization_id, tournament_id)

        removed: list[str] = []
        promoted: list[str] = []
        reserve_queue = list(reserves)

        for team in teams:
            if team.is_reserve:
                continue
            if team.checkin_status != "checked_in":
                logger.info("Team %s did not check in for tournament %s", team.id, tournament_id)

                if auto_remove:
                    await self.team_repo.soft_delete(team.id, organization_id, tournament_id)
                    removed.append(team.id)
                    await self.audit.log(
                        organization_id=organization_id,
                        tournament_id=tournament_id,
                        action="team.auto_removed_noshow",
                        actor_type="system",
                        target_type="team",
                        target_id=team.id,
                        payload={"policy": policy},
                    )

                    # Promote first reserve if available
                    if reserve_queue:
                        reserve = reserve_queue.pop(0)
                        reserve.is_reserve = False
                        reserve.checkin_status = "auto_promoted"
                        await self.session.flush()
                        promoted.append(reserve.id)
                        await self.audit.log(
                            organization_id=organization_id,
                            tournament_id=tournament_id,
                            action="team.reserve_promoted",
                            actor_type="system",
                            target_type="team",
                            target_id=reserve.id,
                            payload={"replaced_team": team.id},
                        )

        return {"removed": removed, "promoted": promoted}
