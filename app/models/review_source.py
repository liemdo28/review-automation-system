from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReviewSource(Base):
    __tablename__ = "review_sources"
    __table_args__ = (
        Index("idx_review_sources_location_platform", "location_id", "platform"),
        Index("idx_review_sources_session_status", "session_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_label: Mapped[str | None] = mapped_column(String(128))
    auth_mode: Mapped[str] = mapped_column(String(32), default="manual_session")
    session_status: Mapped[str] = mapped_column(String(32), default="unknown")
    settings: Mapped[dict | None] = mapped_column(JSONB)
    last_auth_at: Mapped[datetime | None] = mapped_column()
    last_successful_sync_at: Mapped[datetime | None] = mapped_column()
    last_failed_sync_at: Mapped[datetime | None] = mapped_column()
    last_error_message: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    location: Mapped["Location"] = relationship(back_populates="review_sources")
    auth_sessions: Mapped[list["AuthSession"]] = relationship(back_populates="source")
    reviews: Mapped[list["Review"]] = relationship(back_populates="source")
    jobs: Mapped[list["Job"]] = relationship(back_populates="source")
