from datetime import datetime
from sqlalchemy import String, SmallInteger, Text, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
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
    tone_mode: Mapped[str] = mapped_column(String(32), default="gentle_professional")
    confidence_note: Mapped[str | None] = mapped_column(Text)
    reason_summary: Mapped[str | None] = mapped_column(Text)
    issue_tags: Mapped[list[str] | None] = mapped_column(JSONB)
    risk_flags: Mapped[list[str] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    posted_at: Mapped[datetime | None] = mapped_column()
    posted_by_mode: Mapped[str | None] = mapped_column(String(32))
    auto_post_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_auto_post_error: Mapped[str | None] = mapped_column(Text)
    last_auto_post_at: Mapped[datetime | None] = mapped_column()
    decision_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    review: Mapped["Review"] = relationship(back_populates="reply")
