"""
Dispute / support ticket management service.
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.dispute import Dispute, DisputeStatus, DisputeCaseType
from app.database.repositories.audit import AuditRepository
from app.database.repositories.dispute import DisputeRepository
from app.events.publishers import match as match_pub

logger = logging.getLogger(__name__)


class DisputeCaseManager:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DisputeRepository(session)
        self.audit = AuditRepository(session)

    async def open_dispute(
        self,
        organization_id: str,
        tournament_id: str,
        opened_by: str,
        case_type: DisputeCaseType,
        description: str,
        match_id: str | None = None,
        thread_id: str | None = None,
        ai_context: dict | None = None,
    ) -> Dispute:
        dispute = Dispute(
            organization_id=organization_id,
            tournament_id=tournament_id,
            match_id=match_id,
            opened_by=opened_by,
            case_type=case_type,
            description=description,
            status=DisputeStatus.OPEN,
            thread_id=thread_id,
            ai_context=ai_context or {},
        )
        self.session.add(dispute)
        await self.session.flush()
        await self.session.refresh(dispute)

        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action="dispute.opened",
            actor_id=opened_by,
            target_type="dispute",
            target_id=dispute.id,
            payload={"case_type": case_type.value, "match_id": match_id},
        )

        await match_pub.dispute_opened(
            dispute.id, match_id, tournament_id, organization_id, opened_by, case_type.value
        )
        logger.info("Dispute %s opened: %s", dispute.id, case_type.value)
        return dispute

    async def assign(
        self,
        dispute_id: str,
        organization_id: str,
        tournament_id: str,
        assigned_to: str,
        actor_id: str,
    ) -> Dispute:
        d = await self.repo.get_by_id(dispute_id, organization_id, tournament_id)
        if not d:
            raise ValueError(f"Dispute {dispute_id} not found")
        dispute_id = d.id  # normalize short ID to full UUID
        tournament_id = d.tournament_id
        d.assigned_to = assigned_to
        d.status = DisputeStatus.ASSIGNED
        await self.session.flush()
        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action="dispute.assigned",
            actor_id=actor_id,
            target_type="dispute",
            target_id=dispute_id,
            payload={"assigned_to": assigned_to},
        )
        return d

    async def resolve(
        self,
        dispute_id: str,
        organization_id: str,
        tournament_id: str,
        resolved_by: str,
        resolution: str,
        status: DisputeStatus = DisputeStatus.RESOLVED,
    ) -> Dispute:
        d = await self.repo.update_status(
            dispute_id, organization_id, tournament_id,
            status=status,
            resolved_by=resolved_by,
            resolution=resolution,
        )
        if not d:
            raise ValueError(f"Dispute {dispute_id} not found")
        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action=f"dispute.{status.value}",
            actor_id=resolved_by,
            target_type="dispute",
            target_id=dispute_id,
            payload={"resolution": resolution},
        )
        await match_pub.dispute_resolved(
            dispute_id, tournament_id, organization_id, resolved_by, resolution
        )
        return d

    async def add_message(
        self,
        dispute_id: str,
        sender_id: str | None,
        role: str,
        content: str,
    ):
        return await self.repo.add_message(dispute_id, sender_id, role, content)

    async def escalate_to_human(
        self,
        dispute_id: str,
        organization_id: str,
        tournament_id: str,
    ) -> Dispute:
        # Resolve full UUID before any SQL writes
        raw = await self.repo.get_by_id(dispute_id, organization_id, tournament_id)
        if raw:
            dispute_id = raw.id
            tournament_id = raw.tournament_id
        d = await self.repo.update_status(
            dispute_id, organization_id, tournament_id,
            status=DisputeStatus.ESCALATED,
        )
        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action="dispute.escalated",
            actor_type="ai",
            target_type="dispute",
            target_id=dispute_id,
            payload={},
        )
        return d
