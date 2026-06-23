from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    guilds: Mapped[list["Guild"]] = relationship("Guild", back_populates="organization")
    tournaments: Mapped[list["Tournament"]] = relationship("Tournament", back_populates="organization")
    staff_members: Mapped[list["StaffMember"]] = relationship("StaffMember", back_populates="organization")

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug}>"
