import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class MatchStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    CHECKIN_OPEN = "checkin_open"
    CHECKIN_CLOSED = "checkin_closed"
    READY = "ready"
    LIVE = "live"
    AWAITING_SCORE = "awaiting_score"
    UNDER_REVIEW = "under_review"
    PROTESTED = "protested"
    VERIFIED = "verified"
    COMPLETED = "completed"
    VOIDED = "voided"
    RESCHEDULED = "rescheduled"


class Match(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True
    )
    tournament_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True
    )
    bracket_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("brackets.id"), nullable=True, index=True
    )
    round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lobby_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team1_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("teams.id"), nullable=True, index=True
    )
    team2_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("teams.id"), nullable=True, index=True
    )
    winner_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("teams.id"), nullable=True)
    loser_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("teams.id"), nullable=True)
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=MatchStatus.SCHEDULED, index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Flexible score storage: plain int for SE/RR, per-lobby breakdown for BR
    score_team1: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    score_team2: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    score_overridden_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    score_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    private_channel_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    match_log: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="matches")
    bracket: Mapped["Bracket | None"] = relationship("Bracket", back_populates="matches")
    team1: Mapped["Team | None"] = relationship("Team", foreign_keys=[team1_id])
    team2: Mapped["Team | None"] = relationship("Team", foreign_keys=[team2_id])
    winner: Mapped["Team | None"] = relationship("Team", foreign_keys=[winner_id])
    loser: Mapped["Team | None"] = relationship("Team", foreign_keys=[loser_id])
    score_override_user: Mapped["User | None"] = relationship("User", foreign_keys=[score_overridden_by])
    battle_royale_results: Mapped[list["BattleRoyaleResult"]] = relationship(
        "BattleRoyaleResult", back_populates="match"
    )
    disputes: Mapped[list["Dispute"]] = relationship("Dispute", back_populates="match")
    checkins: Mapped[list["CheckIn"]] = relationship("CheckIn", back_populates="match")

    def __repr__(self) -> str:
        return f"<Match id={self.id} round={self.round} status={self.status}>"


class BattleRoyaleResult(Base, TimestampMixin):
    __tablename__ = "battle_royale_results"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    tournament_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True)
    match_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("matches.id"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("teams.id"), nullable=False, index=True)
    lobby_number: Mapped[int] = mapped_column(Integer, nullable=False)
    placement: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kill_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    placement_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bonus_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    penalty_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    @property
    def total_points(self) -> int:
        return self.placement_points + self.kill_points + self.bonus_points - self.penalty_points

    match: Mapped["Match"] = relationship("Match", back_populates="battle_royale_results")
    team: Mapped["Team"] = relationship("Team")

    def __repr__(self) -> str:
        return f"<BRResult match_id={self.match_id} team_id={self.team_id} total={self.total_points}>"
