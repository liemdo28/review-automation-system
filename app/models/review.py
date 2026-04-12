from datetime import datetime, timezone
from sqlalchemy import String, SmallInteger, Text, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Lifecycle states for a review
REVIEW_STATUSES = [
    "new",               # just fetched, not yet analyzed
    "pending_analysis",  # queued for AI analysis
    "analyzed",          # AI analysis complete
    "awaiting_approval", # needs manager review before reply
    "approved",          # manager approved reply
    "auto_replied",      # auto-posted to platform
    "manually_replied",  # manager posted manually
    "escalated",         # escalated to management (high urgency)
    "ignored",           # no action required
    "failed",            # processing error
]


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("platform", "platform_review_id", name="uq_review_platform_id"),
        Index("idx_reviews_location_platform", "location_id", "platform"),
        Index("idx_reviews_rating", "rating"),
        Index("idx_reviews_fetched_at", "fetched_at"),
        Index("idx_reviews_status", "status"),
        Index("idx_reviews_urgency", "urgency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_review_id: Mapped[str] = mapped_column(String(256), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    reviewer_name: Mapped[str | None] = mapped_column(String(256))
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    review_text: Mapped[str | None] = mapped_column(Text)
    review_url: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[datetime | None] = mapped_column()
    has_existing_reply: Mapped[bool] = mapped_column(default=False)
    existing_reply_text: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    # Lifecycle status
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")

    # AI analysis results (denormalized for fast queries)
    sentiment: Mapped[str | None] = mapped_column(String(16))          # positive/neutral/negative/mixed
    urgency: Mapped[str | None] = mapped_column(String(16))             # low/medium/high
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_reply_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    manager_attention_required: Mapped[bool] = mapped_column(Boolean, default=False)
    issue_types_json: Mapped[list | None] = mapped_column(JSONB)        # ["food_quality","service",...]

    fetched_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    location: Mapped["Location"] = relationship(back_populates="reviews")
    reply: Mapped["Reply | None"] = relationship(back_populates="review", uselist=False)
    analysis: Mapped["ReviewAnalysis | None"] = relationship(back_populates="review", uselist=False)
    actions: Mapped[list["ReviewAction"]] = relationship(back_populates="review", order_by="ReviewAction.performed_at")
