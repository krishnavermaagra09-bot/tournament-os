import enum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class RegistrationStatus(str, enum.Enum):
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    MANUALLY_APPROVED = "manually_approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    FLAGGED = "flagged"
    WAITLISTED = "waitlisted"
    CHECKED_IN = "checked_in"


class FormFieldType(str, enum.Enum):
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    NUMBER = "number"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    MULTI_SELECT = "multi_select"
    YES_NO = "yes_no"
    FILE_IMAGE = "file_image"
    ROSTER_ENTRY = "roster_entry"


class RegistrationForm(Base, TimestampMixin):
    __tablename__ = "registration_forms"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False)
    tournament_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="registration_forms")
    fields: Mapped[list["FormField"]] = relationship(
        "FormField", back_populates="form", order_by="FormField.display_order"
    )

    def __repr__(self) -> str:
        return f"<RegistrationForm tournament_id={self.tournament_id} v{self.version}>"


class FormField(Base, TimestampMixin):
    __tablename__ = "form_fields"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False)
    form_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("registration_forms.id"), nullable=False, index=True)
    tournament_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True)
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[FormFieldType] = mapped_column(Enum(FormFieldType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    conditional_logic: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    validation_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    form: Mapped["RegistrationForm"] = relationship("RegistrationForm", back_populates="fields")

    def __repr__(self) -> str:
        return f"<FormField key={self.field_key!r} type={self.field_type}>"


class Registration(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "registrations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True
    )
    tournament_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=False, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("teams.id"), nullable=True
    )
    submitted_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=RegistrationStatus.PENDING, index=True
    )
    form_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    duplicate_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reviewed_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="registrations")
    submitter: Mapped["User"] = relationship("User", back_populates="registrations", foreign_keys=[submitted_by])
    team: Mapped["Team | None"] = relationship("Team", back_populates="registrations")
    evidence_files: Mapped[list["EvidenceFile"]] = relationship(
        "EvidenceFile", back_populates="registration",
        primaryjoin="EvidenceFile.registration_id == Registration.id"
    )

    def __repr__(self) -> str:
        return f"<Registration id={self.id} tournament_id={self.tournament_id} status={self.status}>"
