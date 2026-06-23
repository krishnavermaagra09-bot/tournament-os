"""
BaseRepository enforces organization_id + tournament_id isolation on every query.
No raw query may bypass this guard — the filtering is applied by construction.
"""
from typing import Any, Generic, Type, TypeVar
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, session: AsyncSession, model: Type[ModelT]):
        self.session = session
        self.model = model

    def _base_query(self, organization_id: str, tournament_id: str | None = None):
        q = select(self.model).where(
            getattr(self.model, "organization_id") == organization_id
        )
        if tournament_id and hasattr(self.model, "tournament_id"):
            q = q.where(getattr(self.model, "tournament_id") == tournament_id)
        # Exclude soft-deleted rows if model supports it
        if hasattr(self.model, "deleted_at"):
            q = q.where(getattr(self.model, "deleted_at").is_(None))
        return q

    async def get_by_id(
        self, record_id: str, organization_id: str, tournament_id: str | None = None
    ) -> ModelT | None:
        record_id = record_id.strip()
        # If the caller passed a full UUID (32–36 chars with optional hyphens), use exact match.
        # Otherwise treat it as a prefix and do a LIKE search so users can type short IDs.
        try:
            UUID(record_id)
            is_full_uuid = True
        except (ValueError, AttributeError):
            is_full_uuid = len(record_id) >= 32

        if is_full_uuid:
            q = self._base_query(organization_id, tournament_id).where(
                self.model.id == record_id
            )
        else:
            from sqlalchemy import cast, String
            q = self._base_query(organization_id, tournament_id).where(
                cast(self.model.id, String).like(f"{record_id}%")
            )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def list_all(
        self, organization_id: str, tournament_id: str | None = None,
        limit: int = 100, offset: int = 0
    ) -> list[ModelT]:
        q = self._base_query(organization_id, tournament_id).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def create(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def bulk_create(self, objects: list[ModelT]) -> list[ModelT]:
        for obj in objects:
            self.session.add(obj)
        await self.session.flush()
        return objects

    async def soft_delete(
        self, record_id: str, organization_id: str, tournament_id: str | None = None
    ) -> bool:
        from datetime import datetime, timezone
        obj = await self.get_by_id(record_id, organization_id, tournament_id)
        if not obj:
            return False
        obj.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return True

    async def count(
        self, organization_id: str, tournament_id: str | None = None,
        filters: dict[str, Any] | None = None
    ) -> int:
        from sqlalchemy import func
        q = select(func.count()).select_from(
            self._base_query(organization_id, tournament_id).subquery()
        )
        result = await self.session.execute(q)
        return result.scalar_one()
