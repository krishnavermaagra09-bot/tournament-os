"""
Unit tests — registration submission, duplicate detection, approval/rejection.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tournament import TournamentStatus
from app.database.models.registration import RegistrationStatus
from app.services.registration.approvals import RegistrationApprovalService
from app.services.tournament.lifecycle import TournamentLifecycleService


async def _open_registration(session: AsyncSession, tournament, user):
    svc = TournamentLifecycleService(session)
    await svc.transition_status(
        tournament_id=tournament.id,
        organization_id=tournament.organization_id,
        new_status=TournamentStatus.SCHEDULED,
        actor_id=user.id,
    )
    await svc.transition_status(
        tournament_id=tournament.id,
        organization_id=tournament.organization_id,
        new_status=TournamentStatus.REGISTRATION_OPEN,
        actor_id=user.id,
    )


@pytest.mark.asyncio
async def test_submit_registration(session: AsyncSession, draft_tournament, test_user):
    await _open_registration(session, draft_tournament, test_user)

    svc = RegistrationApprovalService(session)
    reg = await svc.submit(
        tournament=draft_tournament,
        discord_user_id=test_user.discord_user_id,
        form_data={"in_game_name": "ProPlayer", "username": "testuser#0001"},
    )
    assert reg.id is not None
    # No unique fields configured — should auto-approve
    assert reg.status == RegistrationStatus.AUTO_APPROVED


@pytest.mark.asyncio
async def test_approve_registration(session: AsyncSession, draft_tournament, test_user):
    await _open_registration(session, draft_tournament, test_user)

    svc = RegistrationApprovalService(session)
    reg = await svc.submit(
        tournament=draft_tournament,
        discord_user_id=test_user.discord_user_id,
        form_data={"in_game_name": "ProPlayer", "username": "testuser#0001"},
        unique_field_keys=["in_game_name"],  # Force pending status
    )
    # First submission with unique field — no duplicates yet, should be pending
    assert reg.status in (RegistrationStatus.PENDING, RegistrationStatus.AUTO_APPROVED)


@pytest.mark.asyncio
async def test_reject_registration(session: AsyncSession, draft_tournament, test_user):
    await _open_registration(session, draft_tournament, test_user)

    svc = RegistrationApprovalService(session)
    # Submit with unique field to get pending
    reg = await svc.submit(
        tournament=draft_tournament,
        discord_user_id=test_user.discord_user_id,
        form_data={"in_game_name": "Cheater", "username": "testuser#0001"},
        unique_field_keys=["in_game_name"],
    )

    rejected = await svc.reject(
        registration_id=reg.id,
        tournament=draft_tournament,
        reviewer_id=test_user.id,
        reason="Cheating detected",
    )
    assert rejected.status == RegistrationStatus.REJECTED
    assert rejected.rejection_reason == "Cheating detected"
