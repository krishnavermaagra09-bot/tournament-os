"""
Unit tests — tournament creation and lifecycle.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tournament import TournamentStatus, TournamentFormat
from app.services.tournament.creation import TournamentCreationService
from app.services.tournament.lifecycle import TournamentLifecycleService


@pytest.mark.asyncio
async def test_create_tournament(session: AsyncSession, org_and_guild, test_user):
    org, guild = org_and_guild
    svc = TournamentCreationService(session)
    t = await svc.create(
        organization_id=org.id,
        guild_id=guild.id,
        created_by=test_user.id,
        name="Champions Cup 2024",
        game="Valorant",
        format=TournamentFormat.SINGLE_ELIMINATION,
    )
    assert t.id is not None
    assert t.name == "Champions Cup 2024"
    assert t.slug == "champions-cup-2024"
    assert t.status == TournamentStatus.DRAFT


@pytest.mark.asyncio
async def test_create_tournament_unique_slug(session: AsyncSession, org_and_guild, test_user):
    org, guild = org_and_guild
    svc = TournamentCreationService(session)
    t1 = await svc.create(
        organization_id=org.id, guild_id=guild.id, created_by=test_user.id,
        name="Same Name", game="Valorant", format=TournamentFormat.ROUND_ROBIN,
    )
    t2 = await svc.create(
        organization_id=org.id, guild_id=guild.id, created_by=test_user.id,
        name="Same Name", game="Valorant", format=TournamentFormat.ROUND_ROBIN,
    )
    assert t1.slug == "same-name"
    assert t2.slug == "same-name-1"


@pytest.mark.asyncio
async def test_status_transition_valid(session: AsyncSession, draft_tournament, test_user):
    svc = TournamentLifecycleService(session)
    updated = await svc.transition_status(
        tournament_id=draft_tournament.id,
        organization_id=draft_tournament.organization_id,
        new_status=TournamentStatus.SCHEDULED,
        actor_id=test_user.id,
    )
    assert updated.status == TournamentStatus.SCHEDULED


@pytest.mark.asyncio
async def test_status_transition_invalid(session: AsyncSession, draft_tournament, test_user):
    svc = TournamentLifecycleService(session)
    with pytest.raises(ValueError, match="Cannot transition"):
        await svc.transition_status(
            tournament_id=draft_tournament.id,
            organization_id=draft_tournament.organization_id,
            new_status=TournamentStatus.LIVE,
            actor_id=test_user.id,
        )


@pytest.mark.asyncio
async def test_tournament_not_found(session: AsyncSession, org_and_guild):
    org, _ = org_and_guild
    svc = TournamentLifecycleService(session)
    with pytest.raises(ValueError, match="not found"):
        await svc.transition_status(
            tournament_id="nonexistent-id",
            organization_id=org.id,
            new_status=TournamentStatus.SCHEDULED,
            actor_id="actor",
        )
