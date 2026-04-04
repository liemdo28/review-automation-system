from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmailAlert(Base):
    __tablename__ = "email_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"), nullable=False)
    recipient: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="pending")
