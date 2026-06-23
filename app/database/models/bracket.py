from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin, new_uuid


class Bracket(Base, TimestampMixin):
    __tablename__ = "brackets"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False)
    tournament_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="Main Bracket")
    # mirrors TournamentFormat values
    bracket_type: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Format-specific configuration
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Full bracket tree/graph representation — varies by format
    bracket_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="brackets")
    matches: Mapped[list["Match"]] = relationship("Match", back_populates="bracket")
    standings: Mapped[list["Standings"]] = relationship("Standings", back_populates="bracket")

    def __repr__(self) -> str:
        return f"<Bracket id={self.id} type={self.bracket_type} tournament_id={self.tournament_id}>"
