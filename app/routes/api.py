"""REST API endpoints for review operations."""

from __future__ import annotations

import asyncio
import csv
from datetime import date, datetime, timezone
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.ai_reply import generate_reply_bundle
from app.services.review_ops import ReviewFilters, apply_review_filters, count_reviews, derive_review_status
from app.workers.fetch_worker import fetch_all_reviews

router = APIRouter(tags=["api"])


class BulkReviewAction(BaseModel):
    review_ids: list[int]
    tone_mode: str | None = None
    handled_by: str | None = "operator"


class SourceUpdatePayload(BaseModel):
    source_label: str | None = None
    source_url: str | None = None
    auth_mode: str | None = None
    session_status: str | None = None
    settings: dict | None = None
    is_active: bool | None = None


class AuthSessionPayload(BaseModel):
    session_reference: str
    status: str = "active"
    expires_at: datetime | None = None


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(func.count()).select_from(Location))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "error", "database": str(exc)}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    return {
        "total_unreplied_reviews": await count_reviews(db),
        "google_unreplied_reviews": await count_reviews(db, platform="google"),
        "yelp_unreplied_reviews": await count_reviews(db, platform="yelp"),
        "negative_reviews_needing_attention": await count_reviews(db, negative_only=True),
        "reviews_collected_today": (
            await db.execute(select(func.count()).select_from(Review).where(Review.collected_at >= today_start))
        ).scalar()
        or 0,
        "failed_jobs": (
            await db.execute(select(func.count()).select_from(Job).where(Job.status == "failed"))
        ).scalar()
        or 0,
        "auth_expired_jobs": (
            await db.execute(
                select(func.count()).select_from(ReviewSource).where(ReviewSource.session_status == "reauth_required")
            )
        ).scalar()
        or 0,
    }


@router.get("/reviews")
async def list_reviews(
    location_id: int | None = None,
    platform: str | None = None,
    rating: int | None = None,
    status: str | None = None,
    date_preset: str | None = "7d",
    date_from: date | None = None,
    date_to: date | None = None,
    needs_attention_only: bool = True,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    filters = ReviewFilters(
        location_id=location_id,
        platform=platform,
        rating=rating,
        status=status,
        date_preset=date_preset,
        date_from=date_from,
        date_to=date_to,
        needs_attention_only=needs_attention_only,
    )
    query = apply_review_filters(select(Review), filters).order_by(
        Review.review_date.desc().nullslast(),
        Review.last_seen_at.desc(),
    )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    reviews = (await db.execute(query.limit(limit).offset(offset))).scalars().all()

    items = []
    for review in reviews:
        reply = (
            await db.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        latest_job = (
            await db.execute(
                select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        source = await db.get(ReviewSource, review.source_id) if review.source_id else None
        location = await db.get(Location, review.location_id)
        suggestion = (
            await db.execute(
                select(ReplySuggestion)
                .where(ReplySuggestion.review_id == review.id)
                .order_by(ReplySuggestion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        items.append(
            {
                "id": review.id,
                "platform": review.platform,
                "store": location.name if location else None,
                "reviewer_name": review.reviewer_name,
                "rating": review.rating,
                "review_text": review.review_text,
                "review_date": review.review_date.isoformat() if review.review_date else None,
                "has_owner_reply": review.has_owner_reply,
                "detected_owner_reply_text": review.detected_owner_reply_text,
                "source_url": review.source_url,
                "suggested_ai_reply": suggestion.suggestion_text if suggestion else reply.ai_reply_text if reply else None,
                "job_source_status": source.session_status if source else None,
                "review_status": derive_review_status(review, reply, latest_job),
                "is_handled": review.is_handled,
                "tone_mode": suggestion.tone_mode if suggestion else reply.tone_mode if reply else None,
                "reason_summary": suggestion.reason_summary if suggestion else reply.reason_summary if reply else None,
                "confidence_note": suggestion.confidence_note if suggestion else reply.confidence_note if reply else None,
            }
        )

    return {"reviews": items, "count": len(items), "total": total, "offset": offset}


@router.post("/reviews/{review_id}/approve")
async def approve_reply(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (
        await db.execute(select(Reply).where(Reply.review_id == review.id))
    ).scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "No reply found for this review")

    job = Job(
        job_type="post_reply",
        review_id=review.id,
        location_id=review.location_id,
        source_id=review.source_id,
        status="queued",
        payload={"reply_id": reply.id},
    )
    db.add(job)
    reply.status = "approved"
    await db.commit()

    return {"status": "queued", "job_id": job.id}


@router.post("/reviews/{review_id}/suggestions/regenerate")
async def regenerate_reply(
    review_id: int,
    tone_mode: str = settings.default_reply_tone,
    db: AsyncSession = Depends(get_db),
):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    location = await db.get(Location, review.location_id)
    if not location:
        raise HTTPException(404, "Location not found")

    loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
    bundle = await generate_reply_bundle(
        review_text=review.review_text or "",
        rating=review.rating,
        reviewer_name=review.reviewer_name or "Guest",
        restaurant_name=location.name,
        location=loc_str,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        tone_mode=tone_mode,
    )

    suggestion = ReplySuggestion(
        review_id=review.id,
        tone_mode=tone_mode,
        suggestion_text=bundle["suggestion_text"],
        model_name=settings.openai_model,
        sentiment=bundle.get("sentiment"),
        issue_tags=bundle.get("issue_tags"),
        risk_flags=bundle.get("risk_flags"),
        confidence_note=bundle.get("confidence_note"),
        reason_summary=bundle.get("reason_summary"),
        created_by="operator",
    )
    db.add(suggestion)

    reply = (
        await db.execute(select(Reply).where(Reply.review_id == review.id))
    ).scalar_one_or_none()
    if reply:
        reply.ai_reply_text = bundle["suggestion_text"]
        reply.tone_mode = tone_mode
        reply.confidence_note = bundle.get("confidence_note")
        reply.reason_summary = bundle.get("reason_summary")
        reply.issue_tags = bundle.get("issue_tags")
        reply.risk_flags = bundle.get("risk_flags")
    else:
        db.add(
            Reply(
                review_id=review.id,
                ai_reply_text=bundle["suggestion_text"],
                ai_model=settings.openai_model,
                tone_mode=tone_mode,
                confidence_note=bundle.get("confidence_note"),
                reason_summary=bundle.get("reason_summary"),
                issue_tags=bundle.get("issue_tags"),
                risk_flags=bundle.get("risk_flags"),
                status="pending" if review.rating <= 3 else "suggested",
                is_dry_run=settings.dry_run,
            )
        )

    await db.commit()
    return {"status": "ok", "suggestion_id": suggestion.id}


@router.post("/reviews/bulk/regenerate")
async def bulk_regenerate_reviews(payload: BulkReviewAction, db: AsyncSession = Depends(get_db)):
    tone_mode = payload.tone_mode or settings.default_reply_tone
    created = 0
    for review_id in payload.review_ids:
        review = await db.get(Review, review_id)
        if not review:
            continue
        location = await db.get(Location, review.location_id)
        if not location:
            continue

        loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
        bundle = await generate_reply_bundle(
            review_text=review.review_text or "",
            rating=review.rating,
            reviewer_name=review.reviewer_name or "Guest",
            restaurant_name=location.name,
            location=loc_str,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            tone_mode=tone_mode,
        )
        db.add(
            ReplySuggestion(
                review_id=review.id,
                tone_mode=tone_mode,
                suggestion_text=bundle["suggestion_text"],
                model_name=settings.openai_model,
                sentiment=bundle.get("sentiment"),
                issue_tags=bundle.get("issue_tags"),
                risk_flags=bundle.get("risk_flags"),
                confidence_note=bundle.get("confidence_note"),
                reason_summary=bundle.get("reason_summary"),
                created_by=payload.handled_by or "operator",
            )
        )

        reply = (
            await db.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        if reply:
            reply.ai_reply_text = bundle["suggestion_text"]
            reply.tone_mode = tone_mode
            reply.confidence_note = bundle.get("confidence_note")
            reply.reason_summary = bundle.get("reason_summary")
            reply.issue_tags = bundle.get("issue_tags")
            reply.risk_flags = bundle.get("risk_flags")
        else:
            db.add(
                Reply(
                    review_id=review.id,
                    ai_reply_text=bundle["suggestion_text"],
                    ai_model=settings.openai_model,
                    tone_mode=tone_mode,
                    confidence_note=bundle.get("confidence_note"),
                    reason_summary=bundle.get("reason_summary"),
                    issue_tags=bundle.get("issue_tags"),
                    risk_flags=bundle.get("risk_flags"),
                    status="pending" if review.rating <= 3 else "suggested",
                    is_dry_run=settings.dry_run,
                )
            )
        created += 1

    await db.commit()
    return {"status": "ok", "updated_reviews": created}


@router.post("/reviews/bulk/mark-handled")
async def bulk_mark_handled(payload: BulkReviewAction, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    count = 0
    for review_id in payload.review_ids:
        review = await db.get(Review, review_id)
        if not review:
            continue
        review.is_handled = True
        review.handled_at = now
        review.handled_by = payload.handled_by or "operator"
        count += 1
    await db.commit()
    return {"status": "ok", "updated_reviews": count}


@router.get("/reviews/export/selected.csv")
async def export_reviews(review_ids: str, db: AsyncSession = Depends(get_db)):
    ids = [int(value) for value in review_ids.split(",") if value.strip().isdigit()]
    if not ids:
        raise HTTPException(400, "No review ids provided")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "review_id",
            "platform",
            "store",
            "reviewer_name",
            "review_date",
            "rating",
            "review_text",
            "has_owner_reply",
            "detected_owner_reply_text",
            "suggested_reply",
            "status",
            "source_url",
        ]
    )

    for review_id in ids:
        review = await db.get(Review, review_id)
        if not review:
            continue
        location = await db.get(Location, review.location_id)
        reply = (
            await db.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        latest_job = (
            await db.execute(select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()).limit(1))
        ).scalar_one_or_none()
        writer.writerow(
            [
                review.id,
                review.platform,
                location.name if location else "",
                review.reviewer_name or "",
                review.review_date.isoformat() if review.review_date else "",
                review.rating,
                review.review_text or "",
                "yes" if review.has_owner_reply else "no",
                review.detected_owner_reply_text or "",
                reply.ai_reply_text if reply else "",
                derive_review_status(review, reply, latest_job),
                review.source_url or "",
            ]
        )

    output.seek(0)
    filename = f"review-export-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reviews/{review_id}")
async def get_review(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (
        await db.execute(select(Reply).where(Reply.review_id == review.id))
    ).scalar_one_or_none()
    location = await db.get(Location, review.location_id)
    source = await db.get(ReviewSource, review.source_id) if review.source_id else None
    jobs = (
        await db.execute(select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()))
    ).scalars().all()
    suggestions = (
        await db.execute(
            select(ReplySuggestion)
            .where(ReplySuggestion.review_id == review.id)
            .order_by(ReplySuggestion.created_at.desc())
        )
    ).scalars().all()

    return {
        "id": review.id,
        "platform": review.platform,
        "external_review_id": review.external_review_id,
        "reviewer_name": review.reviewer_name,
        "rating": review.rating,
        "review_text": review.review_text,
        "review_date": review.review_date.isoformat() if review.review_date else None,
        "has_owner_reply": review.has_owner_reply,
        "detected_owner_reply_text": review.detected_owner_reply_text,
        "detected_owner_reply_at": review.detected_owner_reply_at.isoformat() if review.detected_owner_reply_at else None,
        "is_handled": review.is_handled,
        "handled_at": review.handled_at.isoformat() if review.handled_at else None,
        "handled_by": review.handled_by,
        "source": {
            "id": source.id,
            "label": source.source_label,
            "url": source.source_url,
            "auth_mode": source.auth_mode,
            "session_status": source.session_status,
        }
        if source
        else None,
        "location": {"id": location.id, "name": location.name, "slug": location.slug} if location else None,
        "reply": {
            "id": reply.id,
            "text": reply.ai_reply_text,
            "status": reply.status,
            "model": reply.ai_model,
            "tone_mode": reply.tone_mode,
            "confidence_note": reply.confidence_note,
            "reason_summary": reply.reason_summary,
            "issue_tags": reply.issue_tags,
            "risk_flags": reply.risk_flags,
            "is_dry_run": reply.is_dry_run,
            "posted_at": reply.posted_at.isoformat() if reply.posted_at else None,
        }
        if reply
        else None,
        "suggestions": [
            {
                "id": item.id,
                "tone_mode": item.tone_mode,
                "suggestion_text": item.suggestion_text,
                "sentiment": item.sentiment,
                "issue_tags": item.issue_tags,
                "risk_flags": item.risk_flags,
                "confidence_note": item.confidence_note,
                "reason_summary": item.reason_summary,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in suggestions
        ],
        "jobs": [
            {
                "id": job.id,
                "job_type": job.job_type,
                "status": job.status,
                "retry_count": job.retry_count,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "error_message": job.error_message,
            }
            for job in jobs
        ],
        "raw_payload": review.raw_payload or review.raw_data,
    }


@router.get("/locations")
async def list_locations(db: AsyncSession = Depends(get_db)):
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    return [
        {
            "id": location.id,
            "slug": location.slug,
            "name": location.name,
            "address": location.address,
            "city": location.city,
            "state": location.state,
            "is_active": location.is_active,
        }
        for location in locations
    ]


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)):
    sources = (await db.execute(select(ReviewSource).order_by(ReviewSource.location_id, ReviewSource.platform))).scalars().all()
    return [
        {
            "id": source.id,
            "location_id": source.location_id,
            "platform": source.platform,
            "source_url": source.source_url,
            "source_label": source.source_label,
            "auth_mode": source.auth_mode,
            "session_status": source.session_status,
            "last_auth_at": source.last_auth_at.isoformat() if source.last_auth_at else None,
            "last_successful_sync_at": source.last_successful_sync_at.isoformat() if source.last_successful_sync_at else None,
            "last_failed_sync_at": source.last_failed_sync_at.isoformat() if source.last_failed_sync_at else None,
            "is_active": source.is_active,
        }
        for source in sources
    ]


@router.patch("/sources/{source_id}")
async def update_source(source_id: int, payload: SourceUpdatePayload, db: AsyncSession = Depends(get_db)):
    source = await db.get(ReviewSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(source, field, value)
    await db.commit()
    return {"status": "ok", "source_id": source.id}


@router.post("/sources/{source_id}/sessions")
async def create_source_session(source_id: int, payload: AuthSessionPayload, db: AsyncSession = Depends(get_db)):
    source = await db.get(ReviewSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    from app.models import AuthSession

    auth_session = AuthSession(
        source_id=source.id,
        platform=source.platform,
        session_reference=payload.session_reference,
        expires_at=payload.expires_at,
        last_validated_at=datetime.now(timezone.utc),
        status=payload.status,
    )
    db.add(auth_session)
    source.session_status = payload.status
    source.last_auth_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok", "session_id": auth_session.id}


@router.post("/fetch/trigger")
async def trigger_fetch(
    location_id: int | None = None,
    platform: str | None = None,
    source_id: int | None = None,
):
    asyncio.create_task(
        fetch_all_reviews(location_id=location_id, platform=platform, source_id=source_id)
    )
    return {"status": "fetch_triggered"}


@router.get("/jobs")
async def list_jobs(limit: int = 20, db: AsyncSession = Depends(get_db)):
    jobs = (
        await db.execute(select(Job).order_by(desc(Job.queued_at)).limit(limit))
    ).scalars().all()
    return [
        {
            "id": job.id,
            "type": job.job_type,
            "status": job.status,
            "review_id": job.review_id,
            "source_id": job.source_id,
            "retry_count": job.retry_count,
            "queued_at": job.queued_at.isoformat() if job.queued_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error": job.error_message,
        }
        for job in jobs
    ]
