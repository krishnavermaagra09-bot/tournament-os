from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SoftDeleteMixin, TimestampMixin, new_uuid


class Guild(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "guilds"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True
    )
    discord_guild_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="guilds")
    tournaments: Mapped[list["Tournament"]] = relationship("Tournament", back_populates="guild")

    def __repr__(self) -> str:
        return f"<Guild id={self.id} discord_guild_id={self.discord_guild_id}>"
