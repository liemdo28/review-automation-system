from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("platform", "platform_review_id", name="uq_review_platform_id"),
        UniqueConstraint("platform", "external_review_id", name="uq_review_platform_external_id"),
        Index("idx_reviews_location_platform", "location_id", "platform"),
        Index("idx_reviews_rating", "rating"),
        Index("idx_reviews_fetched_at", "fetched_at"),
        Index("idx_reviews_date_platform", "review_date", "platform"),
        Index("idx_reviews_owner_reply", "has_owner_reply"),
        Index("idx_reviews_workflow_status", "workflow_status"),
        Index("idx_reviews_auto_reply_eligible", "auto_reply_eligible"),
        Index("idx_reviews_auto_reply_risk_level", "auto_reply_risk_level"),
        Index("idx_reviews_flagged", "is_flagged"),
        Index("idx_reviews_severity_level", "severity_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_review_id: Mapped[str] = mapped_column(String(256), nullable=False)
    external_review_id: Mapped[str] = mapped_column(String(256), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("review_sources.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    reviewer_name: Mapped[str | None] = mapped_column(String(256))
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    review_text: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[datetime | None] = mapped_column()
    has_existing_reply: Mapped[bool] = mapped_column(default=False)
    detected_owner_reply_text: Mapped[str | None] = mapped_column(Text)
    detected_owner_reply_at: Mapped[datetime | None] = mapped_column()
    has_owner_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    collected_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    first_seen_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    is_handled: Mapped[bool] = mapped_column(Boolean, default=False)
    handled_at: Mapped[datetime | None] = mapped_column()
    handled_by: Mapped[str | None] = mapped_column(String(64))
    workflow_status: Mapped[str] = mapped_column(String(32), default="unreplied")
    auto_reply_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_reply_decision_reason: Mapped[str | None] = mapped_column(Text)
    auto_reply_risk_level: Mapped[str | None] = mapped_column(String(16))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    issue_category: Mapped[str | None] = mapped_column(String(32))
    severity_level: Mapped[str | None] = mapped_column(String(16))
    analysis_summary: Mapped[str | None] = mapped_column(Text)
    gm_report_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_by_mode: Mapped[str | None] = mapped_column(String(16))
    policy_version: Mapped[str | None] = mapped_column(String(32))
    last_auto_decision_at: Mapped[datetime | None] = mapped_column()
    fetched_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    location: Mapped["Location"] = relationship(back_populates="reviews")
    reply: Mapped["Reply | None"] = relationship(back_populates="review", uselist=False)
    source: Mapped["ReviewSource | None"] = relationship(back_populates="reviews")
    suggestions: Mapped[list["ReplySuggestion"]] = relationship(back_populates="review")
