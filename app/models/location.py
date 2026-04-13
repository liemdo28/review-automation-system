from datetime import datetime
from sqlalchemy import String, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(2))
    google_account_id: Mapped[str | None] = mapped_column(String(64))
    google_location_id: Mapped[str | None] = mapped_column(String(64))
    yelp_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    fetch_google: Mapped[bool] = mapped_column(Boolean, default=True)
    fetch_yelp: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    reviews: Mapped[list["Review"]] = relationship(back_populates="location")
    review_sources: Mapped[list["ReviewSource"]] = relationship(back_populates="location")
