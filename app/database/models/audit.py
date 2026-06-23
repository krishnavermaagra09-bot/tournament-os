from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin, new_uuid


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    tournament_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True)
    # 'user' | 'bot' | 'system' | 'ai'
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # e.g. 'registration.approved', 'match.score_overridden', 'tournament.status_changed'
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 'registration' | 'match' | 'team' | 'tournament' | ...
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    # Full before/after payload for auditability
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    actor: Mapped["User | None"] = relationship("User", foreign_keys=[actor_id])

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action!r} actor_id={self.actor_id}>"
