from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, Location, Reply, ReplySuggestion, Review, ReviewSource

AUTO_REPLY_CONFIG_KEY = "auto_reply_config"
AUTO_REPLY_POLICY_VERSION = "2026-04-13.v1"
AUTO_POST_SUPPORTED_PLATFORMS = {"google"}
POSITIVE_SENTIMENTS = {"positive"}
NEGATIVE_SENTIMENTS = {"negative", "mixed", "unclear", "ambiguous"}
NEVER_AUTO_POST_TAGS = {
    "food",
    "service",
    "wait_time",
    "cleanliness",
    "pricing",
    "mixed_sentiment",
    "service_recovery",
}
HARD_BLOCK_TERMS = {
    "allergy",
    "allergic",
    "undercooked",
    "raw food",
    "food poisoning",
    "hospital",
    "safety",
    "unsafe",
    "health",
    "discrimination",
    "racist",
    "harassment",
    "threat",
    "lawsuit",
    "lawyer",
    "legal",
    "fraud",
    "theft",
    "stole",
    "refund",
    "chargeback",
    "billing issue",
    "double charged",
}


@dataclass(slots=True)
class AutoReplyDecision:
    allow_auto_post: bool
    risk_level: str
    escalation_required: bool
    decision_reason: str
    recommended_tone_mode: str
    policy_version: str
    workflow_status: str
    queue_auto_post: bool = False
    confidence_score: float = 0.0
    escalation_reason: str | None = None
    matched_blocked_keywords: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_auto_reply_config() -> dict[str, Any]:
    return {
        "auto_reply_enabled": True,
        "auto_post_phase_enabled": False,
        "auto_reply_google_enabled": True,
        "auto_reply_yelp_enabled": False,
        "auto_reply_min_rating": 5,
        "auto_reply_daily_limit": 20,
        "auto_reply_quiet_hours_start": "",
        "auto_reply_quiet_hours_end": "",
        "auto_reply_confidence_threshold": 0.7,
        "auto_reply_blocked_keywords": [],
        "auto_reply_escalation_emails": [],
        "brand_tone_mode": settings.default_reply_tone,
        "max_auto_post_failures": 3,
    }


def normalize_auto_reply_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = default_auto_reply_config()
    if not config:
        return normalized

    for key, value in config.items():
        if value is None:
            continue
        if isinstance(value, str):
            trimmed = value.strip()
            normalized[key] = trimmed if trimmed else normalized.get(key, "")
            continue
        if isinstance(value, list):
            normalized[key] = [item for item in value if item not in (None, "")]
            continue
        normalized[key] = value
    return normalized


def merge_auto_reply_config(
    global_config: Mapping[str, Any] | None,
    location_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = normalize_auto_reply_config(global_config)
    if location_config:
        merged.update(normalize_auto_reply_config(location_config))
    return merged


async def load_global_auto_reply_config(db: AsyncSession) -> dict[str, Any]:
    record = await db.get(AppSetting, AUTO_REPLY_CONFIG_KEY)
    return normalize_auto_reply_config(record.value if record else None)


def load_global_auto_reply_config_sync(session: Session) -> dict[str, Any]:
    record = session.get(AppSetting, AUTO_REPLY_CONFIG_KEY)
    return normalize_auto_reply_config(record.value if record else None)


async def save_global_auto_reply_config(db: AsyncSession, config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_auto_reply_config(config)
    record = await db.get(AppSetting, AUTO_REPLY_CONFIG_KEY)
    if not record:
        record = AppSetting(key=AUTO_REPLY_CONFIG_KEY, value=normalized)
        db.add(record)
    else:
        record.value = normalized
        record.updated_at = datetime.utcnow()
    await db.flush()
    return normalized


def save_global_auto_reply_config_sync(session: Session, config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_auto_reply_config(config)
    record = session.get(AppSetting, AUTO_REPLY_CONFIG_KEY)
    if not record:
        record = AppSetting(key=AUTO_REPLY_CONFIG_KEY, value=normalized)
        session.add(record)
    else:
        record.value = normalized
        record.updated_at = datetime.utcnow()
    session.flush()
    return normalized


async def load_effective_auto_reply_config(
    db: AsyncSession,
    *,
    location: Location | None = None,
) -> dict[str, Any]:
    global_config = await load_global_auto_reply_config(db)
    return merge_auto_reply_config(global_config, location.auto_reply_settings if location else None)


def load_effective_auto_reply_config_sync(
    session: Session,
    *,
    location: Location | None = None,
) -> dict[str, Any]:
    global_config = load_global_auto_reply_config_sync(session)
    return merge_auto_reply_config(global_config, location.auto_reply_settings if location else None)


async def latest_suggestion_for_review(db: AsyncSession, review_id: int) -> ReplySuggestion | None:
    return (
        await db.execute(
            select(ReplySuggestion)
            .where(ReplySuggestion.review_id == review_id)
            .order_by(ReplySuggestion.created_at.desc(), ReplySuggestion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def latest_suggestion_for_review_sync(session: Session, review_id: int) -> ReplySuggestion | None:
    return (
        session.execute(
            select(ReplySuggestion)
            .where(ReplySuggestion.review_id == review_id)
            .order_by(ReplySuggestion.created_at.desc(), ReplySuggestion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def count_auto_posts_today(
    db: AsyncSession,
    *,
    location_id: int,
    now: datetime | None = None,
) -> int:
    reference = now or datetime.utcnow()
    day_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        await db.execute(
            select(func.count())
            .select_from(Reply)
            .join(Review, Review.id == Reply.review_id)
            .where(
                Review.location_id == location_id,
                Reply.posted_by_mode == "auto",
                func.coalesce(Reply.last_auto_post_at, Reply.posted_at) >= day_start,
            )
        )
    ).scalar() or 0


def count_auto_posts_today_sync(
    session: Session,
    *,
    location_id: int,
    now: datetime | None = None,
) -> int:
    reference = now or datetime.utcnow()
    day_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        session.execute(
            select(func.count())
            .select_from(Reply)
            .join(Review, Review.id == Reply.review_id)
            .where(
                Review.location_id == location_id,
                Reply.posted_by_mode == "auto",
                func.coalesce(Reply.last_auto_post_at, Reply.posted_at) >= day_start,
            )
        )
    ).scalar() or 0


def confidence_score(confidence_note: str | None) -> float:
    note = (confidence_note or "").strip().lower()
    if not note:
        return 0.55
    if "high" in note:
        return 0.9
    if "moderate" in note:
        return 0.65
    if "low" in note:
        return 0.35
    return 0.55


def source_auth_is_healthy(source: ReviewSource | None) -> bool:
    if not source:
        return False
    return source.is_active and (source.session_status or "").lower() in {"active", "healthy"}


def _local_now(timezone_name: str | None = None) -> datetime:
    tz_name = timezone_name or settings.review_browser_timezone or "UTC"
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.utcnow()


def _is_quiet_hours(config: Mapping[str, Any], now: datetime | None = None) -> bool:
    start = str(config.get("auto_reply_quiet_hours_start") or "").strip()
    end = str(config.get("auto_reply_quiet_hours_end") or "").strip()
    if not start or not end:
        return False

    now_value = now or _local_now()
    try:
        start_hour, start_minute = [int(part) for part in start.split(":", 1)]
        end_hour, end_minute = [int(part) for part in end.split(":", 1)]
    except ValueError:
        return False

    current_minutes = now_value.hour * 60 + now_value.minute
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    if start_minutes == end_minutes:
        return False
    if start_minutes < end_minutes:
        return start_minutes <= current_minutes < end_minutes
    return current_minutes >= start_minutes or current_minutes < end_minutes


def _blocked_keyword_hits(review_text: str | None, config: Mapping[str, Any]) -> list[str]:
    text = (review_text or "").strip().lower()
    hits: list[str] = []
    if not text:
        return hits

    for keyword in HARD_BLOCK_TERMS:
        if keyword in text:
            hits.append(keyword)
    for keyword in config.get("auto_reply_blocked_keywords", []):
        term = str(keyword).strip().lower()
        if term and term in text and term not in hits:
            hits.append(term)
    return hits


def evaluate_auto_reply(
    review: Review,
    *,
    source: ReviewSource | None,
    config: Mapping[str, Any],
    suggestion_sentiment: str | None = None,
    issue_tags: list[str] | None = None,
    risk_flags: list[str] | None = None,
    confidence_note: str | None = None,
    auto_posts_today: int = 0,
    now: datetime | None = None,
) -> AutoReplyDecision:
    tone_mode = str(config.get("brand_tone_mode") or settings.default_reply_tone)
    sentiment = (suggestion_sentiment or "").strip().lower()
    issue_tag_set = {str(tag).strip().lower() for tag in (issue_tags or []) if tag}
    risk_flag_set = {str(flag).strip().lower() for flag in (risk_flags or []) if flag}
    confidence = confidence_score(confidence_note)
    keyword_hits = _blocked_keyword_hits(review.review_text, config)

    if review.has_owner_reply:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="low",
            escalation_required=False,
            decision_reason="Owner reply already exists on the source page.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="posted",
            confidence_score=confidence,
        )

    if review.rating <= 2:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="high",
            escalation_required=True,
            decision_reason="1–2 star reviews must never auto post.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="escalated",
            confidence_score=confidence,
            escalation_reason="Low-rating review requires manager follow-up.",
            matched_blocked_keywords=keyword_hits or None,
        )

    if keyword_hits:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="high",
            escalation_required=True,
            decision_reason="Hard-block keywords were detected in the review text.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="escalated",
            confidence_score=confidence,
            escalation_reason="Risk-sensitive wording requires manual escalation.",
            matched_blocked_keywords=keyword_hits,
        )

    if review.rating == 3:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason="3-star reviews stay in manual review.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
        )

    if not config.get("auto_reply_enabled", True):
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason="Auto reply is disabled for this configuration.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
        )

    platform_flag = bool(config.get(f"auto_reply_{review.platform}_enabled", False))
    if review.platform not in AUTO_POST_SUPPORTED_PLATFORMS or not platform_flag:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason=f"{review.platform.title()} stays in manual flow for this policy.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
        )

    if review.rating < int(config.get("auto_reply_min_rating", 5) or 5):
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason="Rating does not meet the configured auto-post threshold.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
        )

    if issue_tag_set.intersection(NEVER_AUTO_POST_TAGS) or risk_flag_set:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason="Complaint, mixed sentiment, or risk flags require manual review.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
            matched_blocked_keywords=keyword_hits or None,
        )

    if review.rating == 4 and sentiment not in POSITIVE_SENTIMENTS:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason="4-star reviews need clearly positive sentiment before automation.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
        )

    if review.rating == 4 and not review.review_text:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason="4-star rating-only reviews stay manual because sentiment is ambiguous.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
        )

    threshold = float(config.get("auto_reply_confidence_threshold", 0.7) or 0.7)
    if confidence < threshold:
        return AutoReplyDecision(
            allow_auto_post=False,
            risk_level="medium",
            escalation_required=False,
            decision_reason="AI confidence is below the configured threshold.",
            recommended_tone_mode=tone_mode,
            policy_version=AUTO_REPLY_POLICY_VERSION,
            workflow_status="manual_review_required",
            confidence_score=confidence,
        )

    decision = AutoReplyDecision(
        allow_auto_post=True,
        risk_level="low",
        escalation_required=False,
        decision_reason="Positive review passed the current auto-reply policy checks.",
        recommended_tone_mode=tone_mode,
        policy_version=AUTO_REPLY_POLICY_VERSION,
        workflow_status="auto_post_eligible",
        confidence_score=confidence,
    )

    if not config.get("auto_post_phase_enabled", False):
        decision.decision_reason = "Eligible for auto posting, but auto-post is still paused for this rollout phase."
        return decision

    if not source_auth_is_healthy(source):
        decision.workflow_status = "blocked_auth"
        decision.decision_reason = "Eligible for auto posting, but source auth is not healthy."
        return decision

    if _is_quiet_hours(config, now=now):
        decision.decision_reason = "Eligible for auto posting, but quiet hours are active."
        return decision

    daily_limit = int(config.get("auto_reply_daily_limit", 20) or 20)
    if auto_posts_today >= daily_limit:
        decision.decision_reason = "Eligible for auto posting, but the daily limit has been reached."
        return decision

    decision.queue_auto_post = True
    decision.decision_reason = "Eligible for auto posting and operational checks passed."
    return decision
