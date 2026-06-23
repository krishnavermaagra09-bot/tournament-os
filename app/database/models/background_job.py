from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, TimestampMixin, new_uuid


class BackgroundJob(Base, TimestampMixin):
    """
    Simple DB-backed job queue — no separate task queue service needed for V1.
    FastAPI BackgroundTasks polls this table on a short interval.
    """
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 'pending' | 'running' | 'done' | 'failed'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    run_after: Mapped[str | None] = mapped_column(nullable=True, index=True)
    started_at: Mapped[str | None] = mapped_column(nullable=True)
    completed_at: Mapped[str | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<BackgroundJob type={self.job_type!r} status={self.status}>"
