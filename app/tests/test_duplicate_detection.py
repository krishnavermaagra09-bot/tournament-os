"""
Unit tests — duplicate registration detection.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.registration import RegistrationStatus
from app.services.registration.approvals import RegistrationApprovalService
from app.services.registration.duplicate_detector import DuplicateDetector
from app.services.tournament.lifecycle import TournamentLifecycleService
from app.database.models.tournament import TournamentStatus


@pytest.mark.asyncio
async def test_duplicate_blocked_when_duplicates_not_allowed(
    session: AsyncSession, draft_tournament, test_user, org_and_guild
):
    """When allow_duplicates=False, a duplicate should raise ValueError."""
    # Set allow_duplicates to False
    draft_tournament.allow_duplicates = False
    await session.flush()

    # Open registration
    svc = TournamentLifecycleService(session)
    await svc.transition_status(draft_tournament.id, draft_tournament.organization_id, TournamentStatus.SCHEDULED, test_user.id)
    await svc.transition_status(draft_tournament.id, draft_tournament.organization_id, TournamentStatus.REGISTRATION_OPEN, test_user.id)

    approval_svc = RegistrationApprovalService(session)

    # First submission — should pass
    await approval_svc.submit(
        tournament=draft_tournament,
        discord_user_id=test_user.discord_user_id,
        form_data={"username": "testuser"},
    )

    # Second submission from SAME Discord user — should be blocked
    with pytest.raises(ValueError, match="blocked"):
        await approval_svc.submit(
            tournament=draft_tournament,
            discord_user_id=test_user.discord_user_id,
            form_data={"username": "testuser"},
        )


@pytest.mark.asyncio
async def test_duplicate_flagged_when_allowed(
    session: AsyncSession, draft_tournament, test_user
):
    """When allow_duplicates=True, a duplicate should be flagged but not blocked."""
    draft_tournament.allow_duplicates = True
    await session.flush()

    svc = TournamentLifecycleService(session)
    await svc.transition_status(draft_tournament.id, draft_tournament.organization_id, TournamentStatus.SCHEDULED, test_user.id)
    await svc.transition_status(draft_tournament.id, draft_tournament.organization_id, TournamentStatus.REGISTRATION_OPEN, test_user.id)

    approval_svc = RegistrationApprovalService(session)
    reg1 = await approval_svc.submit(
        tournament=draft_tournament,
        discord_user_id=test_user.discord_user_id,
        form_data={"username": "testuser"},
    )

    # Second submission — flagged but allowed
    reg2 = await approval_svc.submit(
        tournament=draft_tournament,
        discord_user_id=test_user.discord_user_id,
        form_data={"username": "testuser"},
    )
    assert reg2.status == RegistrationStatus.FLAGGED
    assert len(reg2.duplicate_flags) > 0
