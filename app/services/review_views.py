from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.review_ops import ReviewFilters, apply_review_filters, derive_review_status


@dataclass(slots=True)
class SuggestionSummary:
    id: int
    tone_mode: str | None
    suggestion_text: str
    sentiment: str | None
    issue_tags: list[str] | None
    risk_flags: list[str] | None
    confidence_note: str | None
    reason_summary: str | None
    created_at: object | None


@dataclass(slots=True)
class JobSummary:
    id: int
    job_type: str
    status: str
    retry_count: int
    queued_at: object | None
    completed_at: object | None
    error_message: str | None


@dataclass(slots=True)
class ReviewListItem:
    review: Review
    location: Location | None
    source: ReviewSource | None
    reply: Reply | None
    suggestion: SuggestionSummary | None
    latest_job: JobSummary | None
    status: str


def latest_suggestion_subquery():
    ranked = (
        select(
            ReplySuggestion.id.label("suggestion_id"),
            ReplySuggestion.review_id.label("review_id"),
            ReplySuggestion.tone_mode.label("tone_mode"),
            ReplySuggestion.suggestion_text.label("suggestion_text"),
            ReplySuggestion.sentiment.label("sentiment"),
            ReplySuggestion.issue_tags.label("issue_tags"),
            ReplySuggestion.risk_flags.label("risk_flags"),
            ReplySuggestion.confidence_note.label("confidence_note"),
            ReplySuggestion.reason_summary.label("reason_summary"),
            ReplySuggestion.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=ReplySuggestion.review_id,
                order_by=(ReplySuggestion.created_at.desc(), ReplySuggestion.id.desc()),
            )
            .label("rn"),
        )
        .subquery("ranked_suggestions")
    )
    return select(*[column for name, column in ranked.c.items() if name != "rn"]).where(ranked.c.rn == 1).subquery(
        "latest_suggestion"
    )


def latest_job_subquery():
    ranked = (
        select(
            Job.id.label("job_id"),
            Job.review_id.label("review_id"),
            Job.job_type.label("job_type"),
            Job.status.label("status"),
            Job.retry_count.label("retry_count"),
            Job.queued_at.label("queued_at"),
            Job.completed_at.label("completed_at"),
            Job.error_message.label("error_message"),
            func.row_number()
            .over(
                partition_by=Job.review_id,
                order_by=(Job.queued_at.desc(), Job.id.desc()),
            )
            .label("rn"),
        )
        .subquery("ranked_jobs")
    )
    return select(*[column for name, column in ranked.c.items() if name != "rn"]).where(ranked.c.rn == 1).subquery(
        "latest_job"
    )


def build_review_listing_query(filters: ReviewFilters) -> Select:
    suggestion_sq = latest_suggestion_subquery()
    job_sq = latest_job_subquery()

    query = (
        select(
            Review,
            Location,
            ReviewSource,
            Reply,
            suggestion_sq.c.suggestion_id,
            suggestion_sq.c.tone_mode.label("suggestion_tone_mode"),
            suggestion_sq.c.suggestion_text,
            suggestion_sq.c.sentiment.label("suggestion_sentiment"),
            suggestion_sq.c.issue_tags.label("suggestion_issue_tags"),
            suggestion_sq.c.risk_flags.label("suggestion_risk_flags"),
            suggestion_sq.c.confidence_note.label("suggestion_confidence_note"),
            suggestion_sq.c.reason_summary.label("suggestion_reason_summary"),
            suggestion_sq.c.created_at.label("suggestion_created_at"),
            job_sq.c.job_id,
            job_sq.c.job_type.label("latest_job_type"),
            job_sq.c.status.label("latest_job_status"),
            job_sq.c.retry_count.label("latest_job_retry_count"),
            job_sq.c.queued_at.label("latest_job_queued_at"),
            job_sq.c.completed_at.label("latest_job_completed_at"),
            job_sq.c.error_message.label("latest_job_error_message"),
        )
        .join(Location, Location.id == Review.location_id)
        .outerjoin(ReviewSource, ReviewSource.id == Review.source_id)
        .outerjoin(Reply, Reply.review_id == Review.id)
        .outerjoin(suggestion_sq, suggestion_sq.c.review_id == Review.id)
        .outerjoin(job_sq, job_sq.c.review_id == Review.id)
    )
    return apply_review_filters(query, filters)


async def fetch_review_listing(
    db: AsyncSession,
    *,
    filters: ReviewFilters,
    limit: int,
    offset: int = 0,
    order_by: tuple | list | None = None,
) -> list[ReviewListItem]:
    query = build_review_listing_query(filters)
    if order_by:
        query = query.order_by(*order_by)
    rows = (await db.execute(query.limit(limit).offset(offset))).all()
    return [build_review_list_item(row) for row in rows]


async def count_review_listing(db: AsyncSession, *, filters: ReviewFilters) -> int:
    base_query = build_review_listing_query(filters).with_only_columns(Review.id).order_by(None)
    return (await db.execute(select(func.count()).select_from(base_query.subquery()))).scalar() or 0


def build_review_list_item(row) -> ReviewListItem:
    review = row[0]
    location = row[1]
    source = row[2]
    reply = row[3]

    suggestion = None
    if row.suggestion_id is not None:
        suggestion = SuggestionSummary(
            id=row.suggestion_id,
            tone_mode=row.suggestion_tone_mode,
            suggestion_text=row.suggestion_text,
            sentiment=row.suggestion_sentiment,
            issue_tags=row.suggestion_issue_tags,
            risk_flags=row.suggestion_risk_flags,
            confidence_note=row.suggestion_confidence_note,
            reason_summary=row.suggestion_reason_summary,
            created_at=row.suggestion_created_at,
        )

    latest_job = None
    if row.job_id is not None:
        latest_job = JobSummary(
            id=row.job_id,
            job_type=row.latest_job_type,
            status=row.latest_job_status,
            retry_count=row.latest_job_retry_count,
            queued_at=row.latest_job_queued_at,
            completed_at=row.latest_job_completed_at,
            error_message=row.latest_job_error_message,
        )

    return ReviewListItem(
        review=review,
        location=location,
        source=source,
        reply=reply,
        suggestion=suggestion,
        latest_job=latest_job,
        status=derive_review_status(review, reply, _job_namespace(latest_job)),
    )


def _job_namespace(job: JobSummary | None):
    if not job:
        return None
    return SimpleNamespace(status=job.status)
