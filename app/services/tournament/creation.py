"""
Tournament creation service — validates wizard input and persists the tournament.
"""
import re
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tournament import Tournament, TournamentFormat, TournamentStatus, TeamSizeType, EventType
from app.database.models.guild import Guild
from app.database.models.user import User
from app.database.repositories.audit import AuditRepository
from app.database.repositories.tournament import TournamentRepository
from app.events.publishers import tournament as t_pub

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug[:100]


class TournamentCreationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TournamentRepository(session)
        self.audit = AuditRepository(session)

    async def create(
        self,
        organization_id: str,
        guild_id: str,
        created_by: str,
        name: str,
        game: str,
        format: TournamentFormat,
        team_size_type: TeamSizeType = TeamSizeType.SOLO,
        event_type: EventType = EventType.OPEN,
        **kwargs,
    ) -> Tournament:
        base_slug = _slugify(name)
        slug = base_slug
        # Ensure slug uniqueness within the org
        counter = 1
        while await self.repo.get_by_slug(organization_id, slug):
            slug = f"{base_slug}-{counter}"
            counter += 1

        tournament = Tournament(
            organization_id=organization_id,
            guild_id=guild_id,
            created_by=created_by,
            name=name,
            slug=slug,
            game=game,
            format=format,
            team_size_type=team_size_type,
            event_type=event_type,
            status=TournamentStatus.DRAFT,
            **kwargs,
        )

        self.session.add(tournament)
        await self.session.flush()
        await self.session.refresh(tournament)

        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament.id,
            action="tournament.created",
            actor_id=created_by,
            target_type="tournament",
            target_id=tournament.id,
            payload={"name": name, "game": game, "format": format.value},
        )

        await t_pub.tournament_created(tournament.id, organization_id, created_by)
        logger.info("Tournament created: %s (%s)", tournament.id, tournament.name)
        return tournament

    async def update(
        self,
        tournament_id: str,
        organization_id: str,
        actor_id: str,
        **updates,
    ) -> Tournament:
        t = await self.repo.get_by_id(tournament_id, organization_id)
        if not t:
            raise ValueError(f"Tournament {tournament_id} not found")

        old_values = {k: getattr(t, k) for k in updates if hasattr(t, k)}
        for key, value in updates.items():
            if hasattr(t, key):
                setattr(t, key, value)

        await self.session.flush()

        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action="tournament.updated",
            actor_id=actor_id,
            target_type="tournament",
            target_id=tournament_id,
            payload={"before": {k: str(v) for k, v in old_values.items()}, "after": {k: str(v) for k, v in updates.items()}},
        )

        await t_pub.tournament_updated(tournament_id, organization_id, updates)
        return t
