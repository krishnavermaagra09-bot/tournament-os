from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class Team(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True
    )
    tournament_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tag: Mapped[str | None] = mapped_column(String(10), nullable=True)
    captain_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_reserve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checkin_status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_checked_in")
    # Discord artifacts created on approval
    discord_role_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    text_channel_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    voice_channel_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    team_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="teams")
    captain: Mapped["User | None"] = relationship("User", foreign_keys=[captain_id])
    members: Mapped[list["TeamMember"]] = relationship("TeamMember", back_populates="team")
    registrations: Mapped[list["Registration"]] = relationship("Registration", back_populates="team")
    standings: Mapped[list["Standings"]] = relationship("Standings", back_populates="team")

    def __repr__(self) -> str:
        return f"<Team id={self.id} name={self.name!r} tournament_id={self.tournament_id}>"


class TeamMember(Base, TimestampMixin):
    __tablename__ = "team_members"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False)
    tournament_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True
    )
    team_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("teams.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    # 'captain' | 'member' | 'sub'
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    joined_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped["Team"] = relationship("Team", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="team_memberships")

    def __repr__(self) -> str:
        return f"<TeamMember user_id={self.user_id} team_id={self.team_id} role={self.role}>"
