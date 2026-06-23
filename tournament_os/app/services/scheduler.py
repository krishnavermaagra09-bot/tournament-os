"""
Tournament auto-status scheduler.

Runs every 60 seconds and automatically transitions tournament statuses
based on the dates configured in the tournament wizard:

  registration_open_at  → REGISTRATION_OPEN
  registration_close_at → REGISTRATION_CLOSED
  checkin_open_at       → CHECKIN_OPEN
  checkin_close_at      → CHECKIN_CLOSED
  match_start_at        → LIVE (from CHECKIN_CLOSED) + auto-generate bracket
  match_end_at          → COMPLETED (from LIVE / UNDER_REVIEW)

When a tournament transitions to LIVE, the bracket is auto-generated
(if not already generated) so matches start immediately.
"""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def _process_checkin_close(tournament_id: str, organization_id: str) -> None:
    """Run no-show handler when check-in window closes.

    Removes unchecked teams (if auto_removal_policy.enabled) and promotes
    reserves to fill their slots.  Fires a Discord notification with the tally.
    """
    try:
        from app.database.session import AsyncSessionLocal
        from app.services.checkin.noshow_handler import NoShowHandler

        async with AsyncSessionLocal() as session:
            async with session.begin():
                handler = NoShowHandler(session)
                result = await handler.process_noshows(organization_id, tournament_id)

        removed = result.get("removed", [])
        promoted = result.get("promoted", [])
        if removed or promoted:
            logger.info(
                "Scheduler: check-in close — %d removed, %d promoted — tournament=%s",
                len(removed), len(promoted), tournament_id[:8],
            )
    except Exception as exc:
        logger.error(
            "Scheduler: noshow_handler failed for tournament %s: %s",
            tournament_id[:8], exc, exc_info=True,
        )


async def _auto_generate_bracket(tournament_id: str, organization_id: str, t_format) -> None:
    """Generate bracket for a tournament that just went LIVE, if not already done."""
    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.bracket import Bracket
        from app.services.bracket.generator import BracketGenerator
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            existing_q = select(Bracket).where(
                Bracket.tournament_id == tournament_id,
                Bracket.organization_id == organization_id,
            ).limit(1)
            existing = (await session.execute(existing_q)).scalar_one_or_none()
            if existing:
                logger.info(
                    "Scheduler: bracket already exists for tournament %s — skipping generation",
                    tournament_id[:8],
                )
                return

        async with AsyncSessionLocal() as session:
            async with session.begin():
                gen = BracketGenerator(session)
                bracket = await gen.generate(organization_id, tournament_id, t_format)
                logger.info(
                    "Scheduler: auto-generated bracket %s for tournament %s (format=%s)",
                    bracket.id[:8], tournament_id[:8], t_format.value,
                )

        # Fire tournament status event so notification handler announces it
        from app.events.publishers import tournament as t_pub
        await t_pub.tournament_status_changed(
            tournament_id=tournament_id,
            organization_id=organization_id,
            old_status="checkin_closed",
            new_status="live",
        )

    except Exception as exc:
        logger.error(
            "Scheduler: bracket auto-generation failed for tournament %s: %s",
            tournament_id[:8], exc, exc_info=True,
        )


async def _run_once() -> None:
    from app.database.session import AsyncSessionLocal
    from app.database.models.tournament import Tournament, TournamentStatus
    from sqlalchemy import select

    now = datetime.now(tz=timezone.utc)

    watchable_values = [
        TournamentStatus.DRAFT.value,
        TournamentStatus.SCHEDULED.value,
        TournamentStatus.REGISTRATION_OPEN.value,
        TournamentStatus.REGISTRATION_CLOSED.value,
        TournamentStatus.CHECKIN_OPEN.value,
        TournamentStatus.CHECKIN_CLOSED.value,
        TournamentStatus.LIVE.value,
        TournamentStatus.UNDER_REVIEW.value,
    ]

    async with AsyncSessionLocal() as session:
        q = select(Tournament).where(
            Tournament.status.in_(watchable_values),
            Tournament.deleted_at.is_(None),
        )
        tournaments = (await session.execute(q)).scalars().all()

    for t in tournaments:
        try:
            new_status: TournamentStatus | None = None
            st = t.status

            if st in (TournamentStatus.DRAFT, TournamentStatus.SCHEDULED):
                if t.registration_open_at and now >= t.registration_open_at:
                    new_status = TournamentStatus.REGISTRATION_OPEN

            elif st == TournamentStatus.REGISTRATION_OPEN:
                if t.registration_close_at and now >= t.registration_close_at:
                    new_status = TournamentStatus.REGISTRATION_CLOSED

            elif st == TournamentStatus.REGISTRATION_CLOSED:
                if t.checkin_open_at and now >= t.checkin_open_at:
                    new_status = TournamentStatus.CHECKIN_OPEN
                elif t.match_start_at and now >= t.match_start_at:
                    # Skip check-in if no checkin_open_at configured
                    new_status = TournamentStatus.CHECKIN_CLOSED

            elif st == TournamentStatus.CHECKIN_OPEN:
                if t.checkin_close_at and now >= t.checkin_close_at:
                    new_status = TournamentStatus.CHECKIN_CLOSED

            elif st == TournamentStatus.CHECKIN_CLOSED:
                if t.match_start_at and now >= t.match_start_at:
                    new_status = TournamentStatus.LIVE

            elif st in (TournamentStatus.LIVE, TournamentStatus.UNDER_REVIEW):
                if t.match_end_at and now >= t.match_end_at:
                    new_status = TournamentStatus.COMPLETED

            if new_status and t.can_transition_to(new_status):
                going_live = new_status == TournamentStatus.LIVE
                t_format = t.format
                t_id = t.id
                t_org = t.organization_id
                old_status_val = t.status.value

                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        t_row = await session.get(Tournament, t.id)
                        if t_row and t_row.can_transition_to(new_status):
                            t_row.status = new_status
                            logger.info(
                                "Auto-status: %s → %s  tournament=%s (%s)",
                                old_status_val, new_status.value, t.id[:8], t.name,
                            )

                # Fire status-change event for non-LIVE transitions
                # (LIVE fires its own event inside _auto_generate_bracket)
                if not going_live:
                    try:
                        from app.events.publishers import tournament as t_pub
                        await t_pub.tournament_status_changed(
                            tournament_id=t_id,
                            organization_id=t_org,
                            old_status=old_status_val,
                            new_status=new_status.value,
                        )
                    except Exception as exc:
                        logger.warning("Failed to fire status event for %s: %s", t_id[:8], exc)

                # Apply Discord side effects (announcements, channel actions, etc.)
                try:
                    from app.services.discord_effects import apply_status_effects
                    asyncio.create_task(
                        apply_status_effects(
                            tournament_id=t_id,
                            organization_id=t_org,
                            new_status=new_status.value,
                            old_status=old_status_val,
                        )
                    )
                except Exception as exc:
                    logger.warning("Failed to apply discord effects for %s: %s", t_id[:8], exc)

                # When check-in closes, enforce no-show removal
                if new_status == TournamentStatus.CHECKIN_CLOSED:
                    asyncio.create_task(_process_checkin_close(t_id, t_org))

                # When going LIVE, auto-generate the bracket
                if going_live:
                    asyncio.create_task(_auto_generate_bracket(t_id, t_org, t_format))

        except Exception as exc:
            logger.error(
                "Scheduler error for tournament %s: %s", t.id[:8], exc, exc_info=True
            )


async def run_scheduler() -> None:
    """Loop: check all active tournaments every 60 seconds for date-based transitions."""
    logger.info("Tournament auto-status scheduler started (60-second interval)")
    while True:
        try:
            await _run_once()
        except Exception as exc:
            logger.error("Scheduler loop error: %s", exc, exc_info=True)
        await asyncio.sleep(60)
