from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, new_uuid
from sqlalchemy import DateTime, func


class Standings(Base):
    __tablename__ = "standings"
    __table_args__ = (
        UniqueConstraint("tournament_id", "bracket_id", "team_id", name="uq_standings"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    tournament_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True)
    bracket_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("brackets.id"), nullable=True)
    team_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("teams.id"), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    draws: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tiebreaker_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="standings")
    bracket: Mapped["Bracket | None"] = relationship("Bracket", back_populates="standings")
    team: Mapped["Team"] = relationship("Team", back_populates="standings")

    def __repr__(self) -> str:
        return f"<Standings team_id={self.team_id} rank={self.rank} points={self.points}>"
