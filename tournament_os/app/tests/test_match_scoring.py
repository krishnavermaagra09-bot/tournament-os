"""
Unit tests — match scoring.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.match import Match, MatchStatus
from app.database.models.team import Team
from app.services.match.score_handler import ScoreHandler


@pytest.mark.asyncio
async def test_submit_score(session: AsyncSession, draft_tournament, test_user):
    # Create two teams
    team1 = Team(organization_id=draft_tournament.organization_id, tournament_id=draft_tournament.id, name="Team Alpha")
    team2 = Team(organization_id=draft_tournament.organization_id, tournament_id=draft_tournament.id, name="Team Beta")
    session.add(team1)
    session.add(team2)

    # Create a match
    match = Match(
        organization_id=draft_tournament.organization_id,
        tournament_id=draft_tournament.id,
        round=1,
        match_number=1,
        team1_id=team1.id,
        team2_id=team2.id,
        status=MatchStatus.LIVE,
    )
    session.add(match)
    await session.flush()
    await session.refresh(match)

    handler = ScoreHandler(session)
    updated = await handler.submit_score(
        match_id=match.id,
        tournament_id=draft_tournament.id,
        organization_id=draft_tournament.organization_id,
        submitted_by=test_user.id,
        score_team1={"score": 3},
        score_team2={"score": 1},
        winner_id=team1.id,
        loser_id=team2.id,
    )

    assert updated.status == MatchStatus.COMPLETED
    assert updated.winner_id == team1.id
    assert updated.score_team1 == {"score": 3}


@pytest.mark.asyncio
async def test_score_override(session: AsyncSession, draft_tournament, test_user):
    team1 = Team(organization_id=draft_tournament.organization_id, tournament_id=draft_tournament.id, name="Team X")
    team2 = Team(organization_id=draft_tournament.organization_id, tournament_id=draft_tournament.id, name="Team Y")
    session.add_all([team1, team2])

    match = Match(
        organization_id=draft_tournament.organization_id,
        tournament_id=draft_tournament.id,
        round=1, match_number=1,
        team1_id=team1.id, team2_id=team2.id,
        status=MatchStatus.COMPLETED,
        score_team1={"score": 2}, score_team2={"score": 1},
        winner_id=team1.id,
    )
    session.add(match)
    await session.flush()

    handler = ScoreHandler(session)
    updated = await handler.submit_score(
        match_id=match.id,
        tournament_id=draft_tournament.id,
        organization_id=draft_tournament.organization_id,
        submitted_by=test_user.id,
        score_team1={"score": 0},
        score_team2={"score": 2},
        winner_id=team2.id,
        loser_id=team1.id,
        is_override=True,
        override_reason="Score correction by admin",
    )
    assert updated.winner_id == team2.id
    assert updated.score_override_reason == "Score correction by admin"
