from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin, new_uuid


class AISession(Base, TimestampMixin):
    __tablename__ = "ai_sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    guild_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("guilds.id"), nullable=False, index=True)
    # NULL = guild-level query (not tournament-specific)
    tournament_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    # Discord thread snowflake
    thread_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # messages: [{role: str, content: str, ts: str}]
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Set when this session was escalated to a support ticket
    escalated_to: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("disputes.id"), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="ai_sessions")
    escalated_dispute: Mapped["Dispute | None"] = relationship("Dispute", foreign_keys=[escalated_to])

    def __repr__(self) -> str:
        return f"<AISession id={self.id} user_id={self.user_id} msgs={len(self.messages)}>"
