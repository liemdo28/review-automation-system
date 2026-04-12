"""ReviewAnalysis model - stores full structured AI analysis for each review."""
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReviewAnalysis(Base):
    __tablename__ = "review_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"), unique=True, nullable=False)

    # Core AI outputs
    sentiment: Mapped[str | None] = mapped_column(String(16))          # positive/neutral/negative/mixed
    issue_types_json: Mapped[list | None] = mapped_column(JSONB)        # list of detected issue types
    urgency: Mapped[str | None] = mapped_column(String(16))             # low/medium/high
    reply_recommended: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_reply_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    manager_attention_required: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)                   # short internal summary
    suggested_reply: Mapped[str | None] = mapped_column(Text)           # AI-drafted reply

    # Internal notes / escalation reason
    internal_notes: Mapped[str | None] = mapped_column(Text)

    # Metadata for auditability
    model_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    raw_ai_response_json: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    review: Mapped["Review"] = relationship(back_populates="analysis")
