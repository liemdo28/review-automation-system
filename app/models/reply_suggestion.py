from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReplySuggestion(Base):
    __tablename__ = "reply_suggestions"
    __table_args__ = (
        Index("idx_reply_suggestions_review_tone", "review_id", "tone_mode"),
        Index("idx_reply_suggestions_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"), nullable=False)
    tone_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(64))
    sentiment: Mapped[str | None] = mapped_column(String(32))
    issue_tags: Mapped[list[str] | None] = mapped_column(JSONB)
    risk_flags: Mapped[list[str] | None] = mapped_column(JSONB)
    confidence_note: Mapped[str | None] = mapped_column(Text)
    reason_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    created_by: Mapped[str | None] = mapped_column(String(64))

    review: Mapped["Review"] = relationship(back_populates="suggestions")
