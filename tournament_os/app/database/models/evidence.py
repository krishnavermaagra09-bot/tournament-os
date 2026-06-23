from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin, new_uuid


class EvidenceFile(Base, TimestampMixin):
    """
    V1: file blobs stored as BYTEA in PostgreSQL.
    Free, durable, survives Railway redeploys (unlike ephemeral disk).
    Phase 2: migrate to S3/Cloudflare R2 when volume exceeds a few GB.
    """
    __tablename__ = "evidence_files"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    tournament_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=True, index=True)
    registration_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("registrations.id"), nullable=True, index=True)
    dispute_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("disputes.id"), nullable=True, index=True)
    uploaded_by: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    registration: Mapped["Registration | None"] = relationship(
        "Registration", back_populates="evidence_files",
        primaryjoin="EvidenceFile.registration_id == Registration.id"
    )
    dispute: Mapped["Dispute | None"] = relationship(
        "Dispute", back_populates="evidence_files",
        primaryjoin="EvidenceFile.dispute_id == Dispute.id"
    )
    uploader: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return f"<EvidenceFile id={self.id} filename={self.filename!r} size={self.file_size_bytes}>"
