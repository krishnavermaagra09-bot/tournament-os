"""
Analytics event subscribers — listen for domain events and update aggregates.

Calls AnalyticsAggregator to keep computed summaries warm after key events.
"""
import logging

from app.events.bus import event_bus

logger = logging.getLogger(__name__)


async def _warm_tournament_summary(tournament_id: str, organization_id: str) -> None:
    """Re-run the tournament summary query to keep aggregate data fresh."""
    try:
        from app.database.session import AsyncSessionLocal
        from app.services.analytics.aggregator import AnalyticsAggregator

        async with AsyncSessionLocal() as session:
            agg = AnalyticsAggregator(session)
            await agg.tournament_summary(organization_id, tournament_id)
    except Exception as exc:
        logger.warning(
            "Analytics warm failed (tournament=%s): %s", tournament_id[:8], exc
        )


@event_bus.subscribe("RegistrationSubmitted")
async def analytics_on_registration(payload: dict) -> None:
    logger.info(
        "Analytics: registration submitted — tournament=%s reg=%s",
        payload.get("tournament_id", "")[:8],
        payload.get("registration_id", "")[:8],
    )
    await _warm_tournament_summary(
        payload.get("tournament_id", ""),
        payload.get("organization_id", ""),
    )


@event_bus.subscribe("MatchCompleted")
async def analytics_on_match_completed(payload: dict) -> None:
    match_id = payload.get("match_id", "")
    tournament_id = payload.get("tournament_id", "")
    organization_id = payload.get("organization_id", "")
    logger.info(
        "Analytics: match completed — tournament=%s match=%s winner=%s",
        tournament_id[:8], match_id[:8], payload.get("winner_id", "")[:8],
    )
    await _warm_tournament_summary(tournament_id, organization_id)

    # Record match outcome to standings snapshot
    try:
        from app.database.session import AsyncSessionLocal
        from app.services.snapshot.snapshot_service import SnapshotService

        async with AsyncSessionLocal() as session:
            async with session.begin():
                svc = SnapshotService(session)
                await svc.take(
                    organization_id,
                    tournament_id,
                    trigger="match_completed",
                    label=f"After match {match_id[:8]}",
                )
    except Exception as exc:
        logger.debug("Analytics snapshot skipped for match %s: %s", match_id[:8], exc)


@event_bus.subscribe("DisputeOpened")
async def analytics_on_dispute(payload: dict) -> None:
    logger.info(
        "Analytics: dispute opened — tournament=%s dispute=%s type=%s",
        payload.get("tournament_id", "")[:8],
        payload.get("dispute_id", "")[:8],
        payload.get("case_type", ""),
    )
    await _warm_tournament_summary(
        payload.get("tournament_id", ""),
        payload.get("organization_id", ""),
    )


def register_all() -> None:
    pass
