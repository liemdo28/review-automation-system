from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("idx_auth_sessions_source_status", "source_id", "status"),
        Index("idx_auth_sessions_platform_scope_status", "platform", "share_scope", "status"),
        Index("idx_auth_sessions_shared_key", "shared_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("review_sources.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    share_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="source")
    shared_key: Mapped[str | None] = mapped_column(String(255))
    session_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url_override: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column()
    last_validated_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    source: Mapped["ReviewSource"] = relationship(back_populates="auth_sessions")
