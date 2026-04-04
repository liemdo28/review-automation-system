from datetime import datetime, timezone
from sqlalchemy import String, SmallInteger, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("platform", "platform_review_id", name="uq_review_platform_id"),
        Index("idx_reviews_location_platform", "location_id", "platform"),
        Index("idx_reviews_rating", "rating"),
        Index("idx_reviews_fetched_at", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_review_id: Mapped[str] = mapped_column(String(256), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    reviewer_name: Mapped[str | None] = mapped_column(String(256))
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    review_text: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[datetime | None] = mapped_column()
    has_existing_reply: Mapped[bool] = mapped_column(default=False)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    location: Mapped["Location"] = relationship(back_populates="reviews")
    reply: Mapped["Reply | None"] = relationship(back_populates="review", uselist=False)
