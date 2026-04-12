"""ReviewSettings model - per-store, per-platform configuration."""
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReviewSettings(Base):
    __tablename__ = "review_settings"
    __table_args__ = (
        UniqueConstraint("store_id", "platform", name="uq_settings_store_platform"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False)   # location slug
    platform: Mapped[str] = mapped_column(String(16), nullable=False)   # google / yelp / all

    # Auto-reply controls
    auto_reply_google_positive: Mapped[bool] = mapped_column(Boolean, default=False)

    # Alert configuration
    email_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    manager_email: Mapped[str | None] = mapped_column(String(256))

    # Brand voice
    brand_tone: Mapped[str | None] = mapped_column(Text)    # free-text tone instructions
    signature_text: Mapped[str | None] = mapped_column(Text) # appended to all replies

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
