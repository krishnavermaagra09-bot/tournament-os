import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class StaffRole(str, enum.Enum):
    OWNER = "owner"
    SUPER_ADMIN = "super_admin"
    TOURNAMENT_ADMIN = "tournament_admin"
    TOURNAMENT_MANAGER = "tournament_manager"
    REFEREE = "referee"
    MODERATOR = "moderator"
    VERIFIER = "verifier"
    HELPER = "helper"
    SUPPORT = "support"
    ANALYST = "analyst"


class StaffMember(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "staff_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "tournament_id", "role", name="uq_staff"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    role: Mapped[StaffRole] = mapped_column(Enum(StaffRole, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    # NULL = org-wide role; set = scoped to one tournament
    tournament_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=True, index=True
    )
    # Granular RBAC overrides beyond the base role
    permissions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assigned_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="staff_members")
    user: Mapped["User"] = relationship("User", back_populates="staff_roles", foreign_keys=[user_id])
    tournament: Mapped["Tournament | None"] = relationship("Tournament", back_populates="staff_members")

    def has_permission(self, perm: str) -> bool:
        return self.permissions.get(perm, False)

    def __repr__(self) -> str:
        return f"<StaffMember user_id={self.user_id} role={self.role} tournament_id={self.tournament_id}>"
