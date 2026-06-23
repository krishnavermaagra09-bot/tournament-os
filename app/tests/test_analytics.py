"""
Unit tests — analytics aggregator.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics.aggregator import AnalyticsAggregator


@pytest.mark.asyncio
async def test_tournament_summary_empty(session: AsyncSession, draft_tournament):
    agg = AnalyticsAggregator(session)
    summary = await agg.tournament_summary(
        draft_tournament.organization_id, draft_tournament.id
    )
    assert summary["registrations"]["total"] == 0
    assert summary["teams"]["total"] == 0
    assert summary["matches"]["total"] == 0
    assert summary["disputes"]["total"] == 0


@pytest.mark.asyncio
async def test_tournament_summary_with_data(session: AsyncSession, draft_tournament, test_user):
    from app.database.models.team import Team
    from app.database.models.match import Match, MatchStatus

    team = Team(organization_id=draft_tournament.organization_id, tournament_id=draft_tournament.id, name="Analytics Team")
    match = Match(
        organization_id=draft_tournament.organization_id,
        tournament_id=draft_tournament.id,
        round=1, match_number=1,
        status=MatchStatus.COMPLETED,
    )
    session.add_all([team, match])
    await session.flush()

    agg = AnalyticsAggregator(session)
    summary = await agg.tournament_summary(draft_tournament.organization_id, draft_tournament.id)
    assert summary["teams"]["total"] == 1
    assert summary["matches"]["total"] == 1
    assert summary["matches"]["completed"] == 1
