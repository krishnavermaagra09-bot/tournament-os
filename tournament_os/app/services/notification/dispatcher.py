"""
Multi-channel notification dispatcher.
Saves notifications to DB. Discord delivery happens in the bot process;
web dashboard bell reads from DB directly.
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.notification import Notification, NotificationChannel

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def send(
        self,
        organization_id: str,
        title: str,
        body: str,
        channel: NotificationChannel,
        recipient_id: str | None = None,
        tournament_id: str | None = None,
        payload: dict | None = None,
    ) -> Notification:
        n = Notification(
            organization_id=organization_id,
            tournament_id=tournament_id,
            recipient_id=recipient_id,
            channel=channel,
            title=title,
            body=body,
            payload=payload or {},
            sent_at=datetime.now(timezone.utc),
        )
        self.session.add(n)
        await self.session.flush()
        logger.info("Notification queued: %s -> %s (%s)", title, recipient_id, channel.value)
        return n

    async def send_many(
        self,
        organization_id: str,
        title: str,
        body: str,
        channel: NotificationChannel,
        recipient_ids: list[str],
        tournament_id: str | None = None,
        payload: dict | None = None,
    ) -> list[Notification]:
        notifications: list[Notification] = []
        for recipient_id in recipient_ids:
            n = await self.send(
                organization_id=organization_id,
                title=title,
                body=body,
                channel=channel,
                recipient_id=recipient_id,
                tournament_id=tournament_id,
                payload=payload,
            )
            notifications.append(n)
        return notifications

    async def get_unread(
        self, organization_id: str, recipient_id: str, limit: int = 50
    ) -> list[Notification]:
        from sqlalchemy import select
        q = (
            select(Notification)
            .where(Notification.organization_id == organization_id)
            .where(Notification.recipient_id == recipient_id)
            .where(Notification.is_read.is_(False))
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())
