from app.events.bus import event_bus


async def match_started(match_id: str, tournament_id: str, organization_id: str) -> None:
    await event_bus.publish("MatchStarted", {
        "match_id": match_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
    })


async def match_completed(
    match_id: str, tournament_id: str, organization_id: str,
    winner_id: str | None, loser_id: str | None
) -> None:
    await event_bus.publish("MatchCompleted", {
        "match_id": match_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "winner_id": winner_id,
        "loser_id": loser_id,
    })


async def score_submitted(
    match_id: str, tournament_id: str, organization_id: str,
    submitted_by: str, score_team1: dict, score_team2: dict
) -> None:
    await event_bus.publish("ScoreSubmitted", {
        "match_id": match_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "submitted_by": submitted_by,
        "score_team1": score_team1,
        "score_team2": score_team2,
    })


async def dispute_opened(
    dispute_id: str, match_id: str | None, tournament_id: str,
    organization_id: str, opened_by: str, case_type: str
) -> None:
    await event_bus.publish("DisputeOpened", {
        "dispute_id": dispute_id,
        "match_id": match_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "opened_by": opened_by,
        "case_type": case_type,
    })


async def dispute_resolved(
    dispute_id: str, tournament_id: str, organization_id: str,
    resolved_by: str, resolution: str
) -> None:
    await event_bus.publish("DisputeResolved", {
        "dispute_id": dispute_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "resolved_by": resolved_by,
        "resolution": resolution,
    })
