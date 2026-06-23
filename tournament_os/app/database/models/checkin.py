from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin, new_uuid


class CheckIn(Base, TimestampMixin):
    __tablename__ = "checkins"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    tournament_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True)
    # NULL = tournament-level check-in; set = match-level
    match_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("matches.id"), nullable=True, index=True)
    team_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("teams.id"), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 'button' | 'command' | 'auto' | 'admin'
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="button")

    match: Mapped["Match | None"] = relationship("Match", back_populates="checkins")
    team: Mapped["Team | None"] = relationship("Team")
    user: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"<CheckIn team_id={self.team_id} match_id={self.match_id}>"
