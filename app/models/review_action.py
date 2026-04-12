"""ReviewAction model - immutable audit trail of every action taken on a review."""
from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Valid action types
ACTION_TYPES = [
    "fetched",
    "analyzed",
    "drafted",
    "emailed_manager",
    "auto_replied_google",
    "manually_replied",
    "marked_awaiting_approval",
    "approved",
    "escalated",
    "ignored",
    "publish_failed",
    "fetch_failed",
    "analysis_failed",
]


class ReviewAction(Base):
    __tablename__ = "review_actions"
    __table_args__ = (
        Index("idx_review_actions_review_id", "review_id"),
        Index("idx_review_actions_type", "action_type"),
        Index("idx_review_actions_performed_at", "performed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action_status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")  # success/failed
    action_payload_json: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    performed_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    performed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")  # system/manager/<user>

    review: Mapped["Review"] = relationship(back_populates="actions")
