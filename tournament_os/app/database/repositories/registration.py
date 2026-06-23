from sqlalchemy import and_, select

from app.database.models.registration import Registration, RegistrationStatus
from app.database.repositories.base import BaseRepository


class RegistrationRepository(BaseRepository[Registration]):
    def __init__(self, session):
        super().__init__(session, Registration)

    async def get_by_user_and_tournament(
        self, user_id: str, tournament_id: str, organization_id: str
    ) -> Registration | None:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Registration.submitted_by == user_id)
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def list_by_status(
        self, organization_id: str, tournament_id: str, status: RegistrationStatus,
        limit: int = 100, offset: int = 0
    ) -> list[Registration]:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Registration.status == status)
            .order_by(Registration.created_at.asc())
            .limit(limit).offset(offset)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def find_duplicates(
        self, organization_id: str, tournament_id: str,
        field_key: str, value: str
    ) -> list[Registration]:
        """Find approved registrations with matching value for a unique field."""
        from sqlalchemy import cast, String
        from sqlalchemy.dialects.postgresql import JSONB
        q = (
            select(Registration)
            .where(Registration.organization_id == organization_id)
            .where(Registration.tournament_id == tournament_id)
            .where(Registration.deleted_at.is_(None))
            .where(
                Registration.form_data[field_key].astext == value
            )
            .where(
                Registration.status.in_([
                    RegistrationStatus.AUTO_APPROVED,
                    RegistrationStatus.MANUALLY_APPROVED,
                    RegistrationStatus.PENDING,
                ])
            )
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_flagged(
        self, organization_id: str, tournament_id: str
    ) -> list[Registration]:
        q = (
            self._base_query(organization_id, tournament_id)
            .where(Registration.status == RegistrationStatus.FLAGGED)
            .order_by(Registration.created_at.asc())
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def update_status(
        self, registration_id: str, organization_id: str, tournament_id: str,
        status: RegistrationStatus, reviewed_by: str | None = None,
        rejection_reason: str | None = None
    ) -> Registration | None:
        from datetime import datetime, timezone
        reg = await self.get_by_id(registration_id, organization_id, tournament_id)
        if not reg:
            return None
        reg.status = status
        if reviewed_by:
            reg.reviewed_by = reviewed_by
            reg.reviewed_at = datetime.now(timezone.utc)
        if rejection_reason:
            reg.rejection_reason = rejection_reason
        await self.session.flush()
        return reg
