from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Select, and_, exists, func, not_, or_, select

from app.models import Job, Reply, Review


PENDING_REPLY_STATUSES = {"pending", "suggested", "email_sent"}


@dataclass(slots=True)
class ReviewFilters:
    location_id: int | None = None
    platform: str | None = None
    rating: int | None = None
    status: str | None = None
    date_preset: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    needs_attention_only: bool = True


def start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min)


def end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max)


def resolve_date_range(filters: ReviewFilters) -> tuple[datetime | None, datetime | None]:
    now = datetime.utcnow()
    if filters.date_from or filters.date_to:
        return (
            start_of_day(filters.date_from) if filters.date_from else None,
            end_of_day(filters.date_to) if filters.date_to else None,
        )

    preset = (filters.date_preset or "").lower()
    if preset in {"1d", "3d", "7d", "30d"}:
        days = int(preset.replace("d", ""))
        return now - timedelta(days=days), now
    return None, None


def placeholder_google_review_clause():
    return and_(
        Review.platform == "google",
        Review.external_review_id.like("google-%"),
        Review.rating == 0,
        Review.review_date.is_(None),
        or_(Review.reviewer_name == "Anonymous", Review.reviewer_name.is_(None)),
    )


def apply_review_filters(query: Select, filters: ReviewFilters) -> Select:
    query = query.where(not_(placeholder_google_review_clause()))

    if filters.location_id:
        query = query.where(Review.location_id == filters.location_id)
    if filters.platform:
        query = query.where(Review.platform == filters.platform)
    if filters.rating:
        query = query.where(Review.rating == filters.rating)

    date_from, date_to = resolve_date_range(filters)
    if date_from:
        query = query.where(Review.review_date >= date_from)
    if date_to:
        query = query.where(Review.review_date <= date_to)

    if filters.needs_attention_only and not filters.status:
        query = query.where(
            and_(
                Review.is_handled.is_(False),
                or_(Review.has_owner_reply.is_(False), Review.has_owner_reply.is_(None)),
                not_(exists(select(Reply.id).where(and_(Reply.review_id == Review.id, Reply.status == "posted")))),
            )
        )

    status = (filters.status or "").lower()
    if status == "unreplied":
        query = query.where(
            and_(
                Review.is_handled.is_(False),
                or_(Review.has_owner_reply.is_(False), Review.has_owner_reply.is_(None)),
                not_(exists(select(Reply.id).where(Reply.review_id == Review.id))),
            )
        )
    elif status == "replied":
        query = query.where(Review.has_owner_reply.is_(True))
    elif status == "pending_review":
        query = query.where(
            exists(select(Reply.id).where(and_(Reply.review_id == Review.id, Reply.status.in_(PENDING_REPLY_STATUSES))))
        )
    elif status == "approved":
        query = query.where(
            exists(select(Reply.id).where(and_(Reply.review_id == Review.id, Reply.status == "approved")))
        )
    elif status == "posted":
        query = query.where(
            exists(select(Reply.id).where(and_(Reply.review_id == Review.id, Reply.status == "posted")))
        )
    elif status == "failed":
        query = query.where(
            or_(
                exists(select(Reply.id).where(and_(Reply.review_id == Review.id, Reply.status == "failed"))),
                exists(select(Job.id).where(and_(Job.review_id == Review.id, Job.status == "failed"))),
            )
        )
    elif status == "handled":
        query = query.where(Review.is_handled.is_(True))

    return query


def derive_review_status(review: Review, reply: Reply | None, latest_job: Job | None = None) -> str:
    if review.is_handled:
        return "handled"
    if review.has_owner_reply:
        return "replied"
    if reply:
        if reply.status == "posted":
            return "posted"
        if reply.status == "approved":
            return "approved"
        if reply.status in PENDING_REPLY_STATUSES:
            return "pending_review"
        if reply.status == "failed":
            return "failed"
    if latest_job and latest_job.status == "failed":
        return "failed"
    return "unreplied"


async def count_reviews(session, *, platform: str | None = None, negative_only: bool = False) -> int:
    query = apply_review_filters(select(func.count()).select_from(Review), ReviewFilters(platform=platform))
    if negative_only:
        query = query.where(Review.rating <= 3)
    result = await session.execute(query)
    return result.scalar() or 0
