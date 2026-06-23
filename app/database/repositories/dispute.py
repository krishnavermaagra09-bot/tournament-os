from sqlalchemy import select

from app.database.models.dispute import Dispute, DisputeMessage, DisputeStatus
from app.database.repositories.base import BaseRepository


class DisputeRepository(BaseRepository[Dispute]):
    def __init__(self, session):
        super().__init__(session, Dispute)

    async def list_open(
        self, organization_id: str, tournament_id: str
    ) -> list[Dispute]:
        open_statuses = [
            DisputeStatus.OPEN, DisputeStatus.ASSIGNED,
            DisputeStatus.INVESTIGATING, DisputeStatus.WAITING_FOR_RESPONSE,
        ]
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Dispute.status.in_(open_statuses))
            .order_by(Dispute.created_at.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def update_status(
        self, dispute_id: str, organization_id: str, tournament_id: str,
        status: DisputeStatus, resolved_by: str | None = None,
        resolution: str | None = None
    ) -> Dispute | None:
        from datetime import datetime, timezone
        d = await self.get_by_id(dispute_id, organization_id, tournament_id)
        if not d:
            return None
        d.status = status
        if resolved_by:
            d.resolved_by = resolved_by
            d.resolved_at = datetime.now(timezone.utc)
        if resolution:
            d.resolution = resolution
        await self.session.flush()
        return d

    async def add_message(
        self, dispute_id: str, sender_id: str | None,
        role: str, content: str
    ) -> DisputeMessage:
        msg = DisputeMessage(
            dispute_id=dispute_id,
            sender_id=sender_id,
            role=role,
            content=content,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_messages(self, dispute_id: str) -> list[DisputeMessage]:
        q = (
            select(DisputeMessage)
            .where(DisputeMessage.dispute_id == dispute_id)
            .order_by(DisputeMessage.created_at.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())
