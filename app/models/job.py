from datetime import datetime, timezone
from sqlalchemy import String, SmallInteger, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("idx_jobs_status_type", "status", "job_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    review_id: Mapped[int | None] = mapped_column(ForeignKey("reviews.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    payload: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    max_retries: Mapped[int] = mapped_column(SmallInteger, default=3)
    error_message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
