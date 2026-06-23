import enum

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class DisputeStatus(str, enum.Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    INVESTIGATING = "investigating"
    WAITING_FOR_RESPONSE = "waiting_for_response"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    CLOSED = "closed"


class DisputeCaseType(str, enum.Enum):
    WRONG_SCORE = "wrong_score"
    CHEATING_REPORT = "cheating_report"
    RULE_VIOLATION = "rule_violation"
    DISCONNECT = "disconnect"
    REGISTRATION_ISSUE = "registration_issue"
    VERIFICATION_ISSUE = "verification_issue"
    TEAM_ISSUE = "team_issue"
    GENERAL_SUPPORT = "general_support"


class Dispute(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    tournament_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True)
    match_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("matches.id"), nullable=True)
    opened_by: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    assigned_to: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    case_type: Mapped[DisputeCaseType] = mapped_column(Enum(DisputeCaseType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    status: Mapped[DisputeStatus] = mapped_column(
        Enum(DisputeStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=DisputeStatus.OPEN, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Full AI conversation context captured at escalation time
    ai_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(nullable=True)
    # Discord thread snowflake
    thread_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="disputes")
    match: Mapped["Match | None"] = relationship("Match", back_populates="disputes")
    opener: Mapped["User"] = relationship("User", foreign_keys=[opened_by])
    assignee: Mapped["User | None"] = relationship("User", foreign_keys=[assigned_to])
    resolver: Mapped["User | None"] = relationship("User", foreign_keys=[resolved_by])
    messages: Mapped[list["DisputeMessage"]] = relationship("DisputeMessage", back_populates="dispute")
    evidence_files: Mapped[list["EvidenceFile"]] = relationship(
        "EvidenceFile", back_populates="dispute",
        primaryjoin="EvidenceFile.dispute_id == Dispute.id"
    )

    def __repr__(self) -> str:
        return f"<Dispute id={self.id} type={self.case_type} status={self.status}>"


class DisputeMessage(Base, TimestampMixin):
    __tablename__ = "dispute_messages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    dispute_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("disputes.id"), nullable=False, index=True)
    sender_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    # 'user' | 'staff' | 'system' | 'ai'
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    content: Mapped[str] = mapped_column(Text, nullable=False)

    dispute: Mapped["Dispute"] = relationship("Dispute", back_populates="messages")
    sender: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"<DisputeMessage dispute_id={self.dispute_id} role={self.role}>"
