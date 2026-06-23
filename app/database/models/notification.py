import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin, new_uuid


class NotificationChannel(str, enum.Enum):
    DISCORD_DM = "discord_dm"
    DISCORD_CHANNEL = "discord_channel"
    ROLE_PING = "role_ping"
    DASHBOARD_BELL = "dashboard_bell"
    STAFF_INBOX = "staff_inbox"


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False, index=True)
    tournament_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("tournaments.id"), nullable=True, index=True)
    recipient_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel, native_enum=False, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[str | None] = mapped_column(nullable=True)

    recipient: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"<Notification channel={self.channel} title={self.title!r}>"
