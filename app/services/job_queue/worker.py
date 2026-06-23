"""
Background Job Queue Worker.

Processes BackgroundJob records from the database.
Supports: send_notification, send_webhook, generate_bracket,
          advance_round, snapshot, archive_tournament, custom.

Runs every POLL_INTERVAL seconds. Retries up to MAX_ATTEMPTS before marking failed.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.background_job import BackgroundJob
from app.database.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

POLL_INTERVAL = 15  # seconds between polls
MAX_ATTEMPTS = 3


async def _claim_pending_jobs(session: AsyncSession) -> list[BackgroundJob]:
    """Fetch and claim up to 10 pending jobs that are ready to run."""
    now = datetime.now(timezone.utc)
    q = (
        select(BackgroundJob)
        .where(BackgroundJob.status == "pending")
        .where(BackgroundJob.attempts < MAX_ATTEMPTS)
        .where(
            (BackgroundJob.run_after.is_(None)) | (BackgroundJob.run_after <= func.now())
        )
        .order_by(BackgroundJob.created_at.asc())
        .limit(10)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(q)
    jobs = list(result.scalars().all())

    for job in jobs:
        job.status = "running"
        job.started_at = now
        job.attempts = (job.attempts or 0) + 1

    await session.flush()
    return jobs


async def _process_job(job: BackgroundJob, session: AsyncSession) -> None:
    """Dispatch a single job to its handler."""
    jtype = job.job_type
    payload = job.payload or {}

    logger.info("Processing job %s type=%s attempt=%d", job.id[:8], jtype, job.attempts)

    if jtype == "send_notification":
        await _handle_send_notification(payload, session)

    elif jtype == "send_webhook":
        await _handle_send_webhook(payload)

    elif jtype == "generate_bracket":
        await _handle_generate_bracket(payload, session)

    elif jtype == "advance_round":
        await _handle_advance_round(payload, session)

    elif jtype == "snapshot":
        await _handle_snapshot(payload, session)

    elif jtype == "archive_tournament":
        await _handle_archive_tournament(payload, session)

    elif jtype == "noop":
        pass

    else:
        logger.warning("Unknown job type: %s — marking completed", jtype)


# ── Job Handlers ─────────────────────────────────────────────────────────────

async def _handle_send_notification(payload: dict, session: AsyncSession) -> None:
    from app.services.notification.discord_delivery import send_discord_message
    channel_id = payload.get("channel_id")
    content = payload.get("content", "")
    if channel_id:
        await send_discord_message(int(channel_id), content)


async def _handle_send_webhook(payload: dict) -> None:
    from app.services.webhook.webhook_service import WebhookService
    from app.database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        svc = WebhookService(s)
        await svc.dispatch(
            event_type=payload.get("event_type", "job"),
            organization_id=payload.get("organization_id", ""),
            data=payload.get("data", {}),
        )


async def _handle_generate_bracket(payload: dict, session: AsyncSession) -> None:
    from app.services.bracket.generator import BracketGenerator
    from app.database.models.tournament import TournamentFormat
    gen = BracketGenerator(session)
    fmt = TournamentFormat(payload["format"])
    await gen.generate(
        organization_id=payload["organization_id"],
        tournament_id=payload["tournament_id"],
        format=fmt,
        seeding_method=payload.get("seeding_method", "seed"),
    )


async def _handle_advance_round(payload: dict, session: AsyncSession) -> None:
    from app.services.bracket.advancement import BracketAdvancement
    svc = BracketAdvancement(session)
    await svc.generate_next_round(
        organization_id=payload["organization_id"],
        tournament_id=payload["tournament_id"],
        bracket_id=payload["bracket_id"],
    )


async def _handle_snapshot(payload: dict, session: AsyncSession) -> None:
    from app.services.snapshot.snapshot_service import SnapshotService
    svc = SnapshotService(session)
    await svc.take(
        organization_id=payload["organization_id"],
        tournament_id=payload["tournament_id"],
        trigger=payload.get("trigger", "job"),
        label=payload.get("label"),
    )


async def _handle_archive_tournament(payload: dict, session: AsyncSession) -> None:
    from app.services.tournament.lifecycle import TournamentLifecycleService
    from app.database.models.tournament import TournamentStatus
    svc = TournamentLifecycleService(session)
    await svc.change_status(
        tournament_id=payload["tournament_id"],
        organization_id=payload["organization_id"],
        new_status=TournamentStatus.ARCHIVED,
        actor_id="job_queue",
        actor_type="system",
    )


# ── Queue Enqueue Helper ──────────────────────────────────────────────────────

async def enqueue(
    job_type: str,
    payload: dict,
    run_after: datetime | None = None,
) -> None:
    """Enqueue a background job from anywhere in the application."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            job = BackgroundJob(
                job_type=job_type,
                payload=payload,
                status="pending",
                run_after=run_after,
            )
            session.add(job)
    logger.debug("Enqueued job type=%s", job_type)


# ── Worker Loop ───────────────────────────────────────────────────────────────

async def run_job_queue_worker() -> None:
    """Main job queue worker loop — runs forever, polling every POLL_INTERVAL seconds."""
    logger.info("Job queue worker started (poll=%ds, max_attempts=%d)", POLL_INTERVAL, MAX_ATTEMPTS)
    while True:
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    jobs = await _claim_pending_jobs(session)

                    for job in jobs:
                        try:
                            await _process_job(job, session)
                            job.status = "completed"
                            job.completed_at = datetime.now(timezone.utc)
                        except Exception as exc:
                            logger.error(
                                "Job %s type=%s failed (attempt %d/%d): %s",
                                job.id[:8], job.job_type, job.attempts, MAX_ATTEMPTS, exc,
                            )
                            job.error = str(exc)
                            if job.attempts >= MAX_ATTEMPTS:
                                job.status = "failed"
                                logger.error("Job %s exhausted retries — marked failed", job.id[:8])
                            else:
                                job.status = "pending"  # retry next poll

        except Exception as poll_exc:
            logger.error("Job queue poll error: %s", poll_exc)

        await asyncio.sleep(POLL_INTERVAL)
