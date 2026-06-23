from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    discord_user_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    discriminator: Mapped[str | None] = mapped_column(String(4), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    global_settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    registrations: Mapped[list["Registration"]] = relationship(
        "Registration", back_populates="submitter", foreign_keys="Registration.submitted_by"
    )
    team_memberships: Mapped[list["TeamMember"]] = relationship("TeamMember", back_populates="user")
    staff_roles: Mapped[list["StaffMember"]] = relationship(
        "StaffMember", back_populates="user", foreign_keys="[StaffMember.user_id]"
    )
    ai_sessions: Mapped[list["AISession"]] = relationship("AISession", back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} discord_user_id={self.discord_user_id} username={self.username}>"
