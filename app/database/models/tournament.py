import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class TournamentStatus(str, enum.Enum):
    DRAFT = "draft"
    HIDDEN = "hidden"
    TESTING = "testing"
    SCHEDULED = "scheduled"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    CHECKIN_OPEN = "checkin_open"
    CHECKIN_CLOSED = "checkin_closed"
    LIVE = "live"
    UNDER_REVIEW = "under_review"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"


class TournamentFormat(str, enum.Enum):
    SINGLE_ELIMINATION = "single_elimination"
    DOUBLE_ELIMINATION = "double_elimination"
    TRIPLE_ELIMINATION = "triple_elimination"
    ROUND_ROBIN = "round_robin"
    SWISS = "swiss"
    GROUP_STAGE = "group_stage"
    GROUP_STAGE_PLAYOFFS = "group_stage_playoffs"
    SEASON_LEAGUE = "season_league"
    POINTS_LEAGUE = "points_league"
    BATTLE_ROYALE = "battle_royale"
    FREE_FOR_ALL = "free_for_all"
    RACE_TIME_TRIAL = "race_time_trial"
    HYBRID = "hybrid"


class TeamSizeType(str, enum.Enum):
    SOLO = "solo"
    DUO = "duo"
    TRIO = "trio"
    SQUAD = "squad"
    TEAM = "team"
    HYBRID = "hybrid"


class EventType(str, enum.Enum):
    QUALIFIER = "qualifier"
    FINALS = "finals"
    MULTI_STAGE = "multi_stage"
    SCRIMS = "scrims"
    INVITE_ONLY = "invite_only"
    OPEN = "open"


# Valid status transitions — enforced in lifecycle service
VALID_TRANSITIONS: dict[TournamentStatus, list[TournamentStatus]] = {
    TournamentStatus.DRAFT: [TournamentStatus.HIDDEN, TournamentStatus.TESTING, TournamentStatus.SCHEDULED, TournamentStatus.REGISTRATION_OPEN, TournamentStatus.CANCELLED],
    TournamentStatus.HIDDEN: [TournamentStatus.DRAFT, TournamentStatus.TESTING, TournamentStatus.SCHEDULED, TournamentStatus.REGISTRATION_OPEN, TournamentStatus.CANCELLED],
    TournamentStatus.TESTING: [TournamentStatus.DRAFT, TournamentStatus.HIDDEN, TournamentStatus.SCHEDULED, TournamentStatus.REGISTRATION_OPEN, TournamentStatus.CANCELLED],
    TournamentStatus.SCHEDULED: [TournamentStatus.REGISTRATION_OPEN, TournamentStatus.CANCELLED],
    TournamentStatus.REGISTRATION_OPEN: [TournamentStatus.REGISTRATION_CLOSED, TournamentStatus.CANCELLED],
    TournamentStatus.REGISTRATION_CLOSED: [TournamentStatus.CHECKIN_OPEN, TournamentStatus.LIVE, TournamentStatus.CANCELLED],
    TournamentStatus.CHECKIN_OPEN: [TournamentStatus.CHECKIN_CLOSED, TournamentStatus.CANCELLED],
    TournamentStatus.CHECKIN_CLOSED: [TournamentStatus.LIVE, TournamentStatus.CANCELLED],
    TournamentStatus.LIVE: [TournamentStatus.UNDER_REVIEW, TournamentStatus.COMPLETED, TournamentStatus.CANCELLED],
    TournamentStatus.UNDER_REVIEW: [TournamentStatus.LIVE, TournamentStatus.COMPLETED, TournamentStatus.CANCELLED],
    TournamentStatus.COMPLETED: [TournamentStatus.ARCHIVED],
    TournamentStatus.ARCHIVED: [],
    TournamentStatus.CANCELLED: [TournamentStatus.ARCHIVED],
}


class Tournament(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True
    )
    guild_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("guilds.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    game: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[TournamentFormat] = mapped_column(Enum(TournamentFormat, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=EventType.OPEN)
    team_size_type: Mapped[TeamSizeType] = mapped_column(Enum(TeamSizeType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=TeamSizeType.SOLO)
    min_team_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_team_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_teams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_players: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prize_pool: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[TournamentStatus] = mapped_column(
        Enum(TournamentStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=TournamentStatus.DRAFT, index=True
    )
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")
    registration_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkin_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkin_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    round_duration_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tiebreaker_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    seeding_method: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    dispute_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_removal_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reserve_handling: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    allow_duplicates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    branding: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    channel_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 2.0: Autonomous mode — the engine manages the full tournament lifecycle
    autonomous_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 2.0: Team hub settings — auto-create private Discord categories for each team
    team_hub_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 2.0: Match channel config — auto-create per-match text channels
    match_channel_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 2.0: Group stage config — number of groups, teams per group, advancement rules
    group_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 2.0: Feature flags — per-tournament toggles without schema changes
    # Example: {"score_auto_approval": true, "checkin_required": false,
    #            "allow_score_edit": false, "ai_moderation": true}
    feature_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="tournaments")
    guild: Mapped["Guild"] = relationship("Guild", back_populates="tournaments")
    registrations: Mapped[list["Registration"]] = relationship("Registration", back_populates="tournament")
    teams: Mapped[list["Team"]] = relationship("Team", back_populates="tournament")
    matches: Mapped[list["Match"]] = relationship("Match", back_populates="tournament")
    brackets: Mapped[list["Bracket"]] = relationship("Bracket", back_populates="tournament")
    standings: Mapped[list["Standings"]] = relationship("Standings", back_populates="tournament")
    disputes: Mapped[list["Dispute"]] = relationship("Dispute", back_populates="tournament")
    staff_members: Mapped[list["StaffMember"]] = relationship("StaffMember", back_populates="tournament")
    registration_forms: Mapped[list["RegistrationForm"]] = relationship("RegistrationForm", back_populates="tournament")

    def can_transition_to(self, new_status: TournamentStatus) -> bool:
        return new_status in VALID_TRANSITIONS.get(self.status, [])

    def __repr__(self) -> str:
        return f"<Tournament id={self.id} name={self.name!r} status={self.status} autonomous={self.autonomous_mode}>"
