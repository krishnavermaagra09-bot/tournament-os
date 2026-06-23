"""
Tournament snapshot — immutable JSON dump of tournament state at a lifecycle point.

Taken automatically at:
  - bracket_generated
  - round_complete
  - tournament_completed

Also taken manually via /override snapshot or Control Panel.
"""
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, TimestampMixin, new_uuid


class TournamentSnapshot(Base, TimestampMixin):
    __tablename__ = "tournament_snapshots"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    tournament_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)

    # What triggered this snapshot: 'bracket_generated' | 'round_complete' |
    # 'tournament_completed' | 'manual' | 'pre_override'
    trigger: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Optional label (e.g. "Round 2 complete")
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Full JSON dump of tournament state at snapshot time
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    def __repr__(self) -> str:
        return (
            f"<TournamentSnapshot tournament={self.tournament_id[:8]} trigger={self.trigger!r}>"
        )
