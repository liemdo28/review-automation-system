from datetime import datetime, timezone
from sqlalchemy import String, SmallInteger, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Reply(Base):
    __tablename__ = "replies"
    __table_args__ = (
        Index("idx_replies_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"), unique=True, nullable=False)
    ai_reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    ai_model: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    posted_at: Mapped[datetime | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    review: Mapped["Review"] = relationship(back_populates="reply")
