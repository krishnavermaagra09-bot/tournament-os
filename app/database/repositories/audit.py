from sqlalchemy import select

from app.database.models.audit import AuditLog
from app.database.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    def __init__(self, session):
        super().__init__(session, AuditLog)

    async def log(
        self,
        organization_id: str,
        action: str,
        actor_id: str | None = None,
        actor_type: str = "user",
        tournament_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        payload: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            organization_id=organization_id,
            tournament_id=tournament_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=payload or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_for_target(
        self, organization_id: str, target_type: str, target_id: str,
        limit: int = 50
    ) -> list[AuditLog]:
        q = (
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.target_type == target_type)
            .where(AuditLog.target_id == target_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_for_tournament(
        self, organization_id: str, tournament_id: str,
        limit: int = 200, offset: int = 0
    ) -> list[AuditLog]:
        q = (
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.tournament_id == tournament_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit).offset(offset)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())
