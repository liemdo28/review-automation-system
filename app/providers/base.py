from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from typing import Any


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


class ProviderConfigError(ProviderError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="config_error", retryable=False, details=details)


class ProviderAuthRequiredError(ProviderError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="auth_required", retryable=False, details=details)


class ProviderFetchError(ProviderError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="fetch_error", retryable=retryable, details=details)


class ProviderPostError(ProviderError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="post_error", retryable=retryable, details=details)


@dataclass(slots=True)
class ProviderReview:
    external_review_id: str
    platform: str
    source_url: str
    reviewer_name: str | None = None
    rating: int = 0
    review_text: str | None = None
    review_date: datetime | None = None
    has_owner_reply: bool = False
    detected_owner_reply_text: str | None = None
    detected_owner_reply_at: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class ReviewProvider(ABC):
    platform: str

    def __init__(self, source, auth_session=None) -> None:
        self.source = source
        self.auth_session = auth_session
        self.settings = source.settings or {}

    @abstractmethod
    async def validate_session(self) -> tuple[bool, str]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_reviews(self) -> list[ProviderReview]:
        raise NotImplementedError

    async def post_reply(self, review, reply_text: str) -> dict[str, Any]:
        raise ProviderConfigError(
            f"Direct reply posting is not supported for {self.platform}",
            details={"platform": self.platform, "source_id": self.source.id},
        )

    @staticmethod
    def parse_rating(text: str | None) -> int:
        if not text:
            return 0
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            return 0
        return max(0, min(5, round(float(match.group(1)))))

    @staticmethod
    def normalize_text(text: str | None) -> str | None:
        if text is None:
            return None

        cleaned = text.replace("\xa0", " ").strip()
        if not cleaned:
            return None

        suspicious_tokens = ("Ã", "Â", "Ä", "â", "ð", "\x85")
        if any(token in cleaned for token in suspicious_tokens):
            try:
                repaired = cleaned.encode("latin1").decode("utf-8")
                if repaired and repaired != cleaned:
                    cleaned = repaired
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass

        return cleaned

    @staticmethod
    def parse_datetime(text: str | None) -> datetime | None:
        if not text:
            return None

        raw = ReviewProvider.normalize_text(text) or ""
        now = datetime.utcnow()
        vi_relative = re.match(
            r"(\d+)\s+(phút|giờ|ngày|tuần|tháng|năm)\s+trước",
            raw,
            re.IGNORECASE,
        )
        if vi_relative:
            value = int(vi_relative.group(1))
            unit = vi_relative.group(2).lower()
            deltas = {
                "phút": timedelta(minutes=value),
                "giờ": timedelta(hours=value),
                "ngày": timedelta(days=value),
                "tuần": timedelta(weeks=value),
                "tháng": timedelta(days=value * 30),
                "năm": timedelta(days=value * 365),
            }
            return now - deltas.get(unit, timedelta())

        relative = re.match(
            r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago",
            raw,
            re.IGNORECASE,
        )
        if relative:
            value = int(relative.group(1))
            unit = relative.group(2).lower()
            deltas = {
                "minute": timedelta(minutes=value),
                "hour": timedelta(hours=value),
                "day": timedelta(days=value),
                "week": timedelta(weeks=value),
                "month": timedelta(days=value * 30),
                "year": timedelta(days=value * 365),
            }
            return now - deltas.get(unit, timedelta())

        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None
