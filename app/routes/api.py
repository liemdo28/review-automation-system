"""
REST API Endpoints
==================
Full production API for the review management system.

Sync:        POST /api/reviews/sync/{google|yelp|all}
Listing:     GET  /api/reviews  (filterable by platform, status, urgency, rating, store)
Actions:     POST /api/reviews/{id}/{analyze|draft|approve|reply|escalate|ignore}
Settings:    GET/PUT /api/review-settings
Reporting:   GET /api/reviews/metrics  /report/daily  /report/weekly
Jobs:        GET /api/jobs
Health:      GET /api/health  /stats
"""
import asyncio
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Location, Review, Reply, Job, FetchLog,
    ReviewAnalysis, ReviewAction, ReviewSettings,
)
from app.workers.fetch_worker import fetch_all_reviews, _fetch_google, _fetch_yelp
from app.config import settings

router = APIRouter(tags=["api"])


# ── Health / Stats ────────────────────────────────────────────────────────────

@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(func.count()).select_from(Location))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    posted = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "posted")
    )).scalar() or 0
    pending = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status.in_(["pending", "email_sent"]))
    )).scalar() or 0
    suggested = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "suggested")
    )).scalar() or 0
    escalated = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "escalated")
    )).scalar() or 0
    awaiting = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "awaiting_approval")
    )).scalar() or 0
    queued_jobs = (await db.execute(
        select(func.count()).select_from(Job).where(Job.status == "queued")
    )).scalar() or 0

    locations = (await db.execute(
        select(Location).where(Location.is_active == True)  # noqa: E712
    )).scalars().all()
    loc_stats = []
    for loc in locations:
        rc = (await db.execute(
            select(func.count()).select_from(Review).where(Review.location_id == loc.id)
        )).scalar() or 0
        rp = (await db.execute(
            select(func.count()).select_from(Reply).where(
                and_(Reply.status == "posted",
                     Reply.review_id.in_(select(Review.id).where(Review.location_id == loc.id)))
            )
        )).scalar() or 0
        loc_stats.append({"id": loc.id, "slug": loc.slug, "name": loc.name,
                           "reviews": rc, "replies": rp})

    return {
        "total_reviews": total,
        "total_replies_posted": posted,
        "pending_replies": pending,
        "yelp_suggestions": suggested,
        "escalated_reviews": escalated,
        "awaiting_approval": awaiting,
        "queued_jobs": queued_jobs,
        "locations": loc_stats,
    }


# ── Sync Triggers ─────────────────────────────────────────────────────────────

@router.post("/reviews/sync/all")
async def sync_all():
    """Trigger a full fetch cycle for all locations (Google + Yelp)."""
    asyncio.create_task(fetch_all_reviews())
    return {"status": "triggered", "message": "Full sync started for all locations"}


@router.post("/reviews/sync/google")
async def sync_google(db: AsyncSession = Depends(get_db)):
    """Trigger Google fetch for all active locations."""
    locations = (await db.execute(
        select(Location).where(Location.is_active == True, Location.fetch_google == True)  # noqa: E712
    )).scalars().all()

    async def _run():
        for loc in locations:
            if loc.google_location_id:
                await _fetch_google(loc)

    asyncio.create_task(_run())
    return {"status": "triggered", "locations": len(locations)}


@router.post("/reviews/sync/yelp")
async def sync_yelp(db: AsyncSession = Depends(get_db)):
    """Trigger Yelp fetch for all active locations."""
    locations = (await db.execute(
        select(Location).where(Location.is_active == True, Location.fetch_yelp == True)  # noqa: E712
    )).scalars().all()

    async def _run():
        for loc in locations:
            if loc.yelp_url:
                await _fetch_yelp(loc)

    asyncio.create_task(_run())
    return {"status": "triggered", "locations": len(locations)}


@router.post("/fetch/trigger")
async def trigger_fetch():
    """Legacy endpoint — kept for backwards compat."""
    asyncio.create_task(fetch_all_reviews())
    return {"status": "fetch_triggered"}


# ── Review Listing ────────────────────────────────────────────────────────────

@router.get("/reviews")
async def list_reviews(
    location_id: int | None = None,
    store_id: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    urgency: str | None = None,
    is_sensitive: bool | None = None,
    rating_lte: int | None = None,
    rating_gte: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(Review).order_by(desc(Review.fetched_at))

    if location_id:
        query = query.where(Review.location_id == location_id)
    if store_id:
        loc_row = (await db.execute(
            select(Location).where(Location.slug == store_id)
        )).scalar_one_or_none()
        if loc_row:
            query = query.where(Review.location_id == loc_row.id)
    if platform:
        query = query.where(Review.platform == platform)
    if status:
        query = query.where(Review.status == status)
    if urgency:
        query = query.where(Review.urgency == urgency)
    if is_sensitive is not None:
        query = query.where(Review.is_sensitive == is_sensitive)
    if rating_lte is not None:
        query = query.where(Review.rating <= rating_lte)
    if rating_gte is not None:
        query = query.where(Review.rating >= rating_gte)

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0

    reviews = (await db.execute(query.limit(limit).offset(offset))).scalars().all()

    items = []
    for r in reviews:
        reply = (await db.execute(
            select(Reply).where(Reply.review_id == r.id)
        )).scalar_one_or_none()
        loc = await db.get(Location, r.location_id)
        items.append({
            "id": r.id,
            "platform": r.platform,
            "store": loc.name if loc else None,
            "store_slug": loc.slug if loc else None,
            "reviewer_name": r.reviewer_name,
            "rating": r.rating,
            "review_text": (r.review_text or "")[:300],
            "review_date": r.review_date.isoformat() if r.review_date else None,
            "status": r.status,
            "sentiment": r.sentiment,
            "urgency": r.urgency,
            "is_sensitive": r.is_sensitive,
            "auto_reply_allowed": r.auto_reply_allowed,
            "manager_attention_required": r.manager_attention_required,
            "issue_types": r.issue_types_json or [],
            "reply_status": reply.status if reply else None,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        })

    return {"reviews": items, "total": total, "count": len(items), "offset": offset}


@router.get("/reviews/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)):
    """KPI metrics for reporting dashboard."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    total = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    new_today = (await db.execute(
        select(func.count()).select_from(Review).where(Review.fetched_at >= day_ago)
    )).scalar() or 0
    unreplied = (await db.execute(
        select(func.count()).select_from(Review).where(
            Review.has_existing_reply == False,  # noqa: E712
            Review.status.notin_(["auto_replied", "manually_replied", "ignored"])
        )
    )).scalar() or 0
    auto_replied = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "auto_replied")
    )).scalar() or 0
    escalated = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "escalated")
    )).scalar() or 0
    awaiting = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "awaiting_approval")
    )).scalar() or 0
    sensitive = (await db.execute(
        select(func.count()).select_from(Review).where(Review.is_sensitive == True)  # noqa: E712
    )).scalar() or 0

    sentiments: dict = {}
    for s in ["positive", "neutral", "negative", "mixed"]:
        cnt = (await db.execute(
            select(func.count()).select_from(Review).where(Review.sentiment == s)
        )).scalar() or 0
        sentiments[s] = cnt

    avg_rating = (await db.execute(
        select(func.avg(Review.rating)).select_from(Review)
    )).scalar()

    # Top complaint categories from review_analysis
    analyses = (await db.execute(
        select(ReviewAnalysis.issue_types_json)
        .where(ReviewAnalysis.issue_types_json.isnot(None))
        .limit(500)
    )).scalars().all()
    issue_counts: dict[str, int] = {}
    for issue_list in analyses:
        if isinstance(issue_list, list):
            for issue in issue_list:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
    top_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    platforms: dict = {}
    for p in ["google", "yelp"]:
        cnt = (await db.execute(
            select(func.count()).select_from(Review).where(Review.platform == p)
        )).scalar() or 0
        platforms[p] = cnt

    return {
        "total_reviews": total,
        "new_today": new_today,
        "unreplied_reviews": unreplied,
        "auto_replied_count": auto_replied,
        "escalated_count": escalated,
        "awaiting_approval_count": awaiting,
        "sensitive_count": sensitive,
        "average_rating": round(float(avg_rating), 2) if avg_rating else None,
        "sentiment_breakdown": sentiments,
        "platform_breakdown": platforms,
        "top_complaint_categories": [{"issue": k, "count": v} for k, v in top_issues],
        "auto_reply_rate": round(auto_replied / total * 100, 1) if total else 0,
        "generated_at": now.isoformat(),
    }


@router.get("/reviews/report/daily")
async def daily_report(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)
    reviews = (await db.execute(
        select(Review).where(Review.fetched_at >= since).order_by(desc(Review.fetched_at))
    )).scalars().all()
    return {
        "period": "last_24h",
        "total_new_reviews": len(reviews),
        "by_platform": {
            "google": sum(1 for r in reviews if r.platform == "google"),
            "yelp": sum(1 for r in reviews if r.platform == "yelp"),
        },
        "by_rating": {str(i): sum(1 for r in reviews if r.rating == i) for i in range(1, 6)},
        "escalated": sum(1 for r in reviews if r.status == "escalated"),
        "auto_replied": sum(1 for r in reviews if r.status == "auto_replied"),
        "generated_at": now.isoformat(),
    }


@router.get("/reviews/report/weekly")
async def weekly_report(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    reviews = (await db.execute(
        select(Review).where(Review.fetched_at >= since).order_by(desc(Review.fetched_at))
    )).scalars().all()
    return {
        "period": "last_7_days",
        "total_new_reviews": len(reviews),
        "by_platform": {
            "google": sum(1 for r in reviews if r.platform == "google"),
            "yelp": sum(1 for r in reviews if r.platform == "yelp"),
        },
        "by_rating": {str(i): sum(1 for r in reviews if r.rating == i) for i in range(1, 6)},
        "escalated": sum(1 for r in reviews if r.status == "escalated"),
        "auto_replied": sum(1 for r in reviews if r.status == "auto_replied"),
        "sensitive": sum(1 for r in reviews if r.is_sensitive),
        "generated_at": now.isoformat(),
    }


# ── Single Review ─────────────────────────────────────────────────────────────

@router.get("/reviews/{review_id}")
async def get_review(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (await db.execute(
        select(Reply).where(Reply.review_id == review.id)
    )).scalar_one_or_none()
    location = await db.get(Location, review.location_id)
    analysis = (await db.execute(
        select(ReviewAnalysis).where(ReviewAnalysis.review_id == review.id)
    )).scalar_one_or_none()
    actions = (await db.execute(
        select(ReviewAction).where(ReviewAction.review_id == review.id)
        .order_by(ReviewAction.performed_at.asc())
    )).scalars().all()

    return {
        "id": review.id,
        "platform": review.platform,
        "platform_review_id": review.platform_review_id,
        "reviewer_name": review.reviewer_name,
        "rating": review.rating,
        "review_text": review.review_text,
        "review_url": review.review_url,
        "review_date": review.review_date.isoformat() if review.review_date else None,
        "status": review.status,
        "sentiment": review.sentiment,
        "urgency": review.urgency,
        "is_sensitive": review.is_sensitive,
        "auto_reply_allowed": review.auto_reply_allowed,
        "manager_attention_required": review.manager_attention_required,
        "issue_types": review.issue_types_json or [],
        "fetched_at": review.fetched_at.isoformat() if review.fetched_at else None,
        "location": {
            "id": location.id, "name": location.name, "slug": location.slug,
            "address": location.address,
        } if location else None,
        "analysis": {
            "id": analysis.id,
            "sentiment": analysis.sentiment,
            "urgency": analysis.urgency,
            "issue_types": analysis.issue_types_json or [],
            "summary": analysis.summary,
            "suggested_reply": analysis.suggested_reply,
            "auto_reply_allowed": analysis.auto_reply_allowed,
            "manager_attention_required": analysis.manager_attention_required,
            "internal_notes": analysis.internal_notes,
            "model_name": analysis.model_name,
            "prompt_version": analysis.prompt_version,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        } if analysis else None,
        "reply": {
            "id": reply.id,
            "text": reply.ai_reply_text,
            "status": reply.status,
            "model": reply.ai_model,
            "is_dry_run": reply.is_dry_run,
            "posted_at": reply.posted_at.isoformat() if reply.posted_at else None,
            "error_message": reply.error_message,
        } if reply else None,
        "actions": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "action_status": a.action_status,
                "payload": a.action_payload_json,
                "error": a.error_message,
                "performed_by": a.performed_by,
                "performed_at": a.performed_at.isoformat() if a.performed_at else None,
            }
            for a in actions
        ],
    }


# ── Review Actions ────────────────────────────────────────────────────────────

@router.post("/reviews/{review_id}/analyze")
async def trigger_analyze(review_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger or re-trigger AI analysis for a specific review."""
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    job = Job(job_type="analyze_review", review_id=review.id,
              location_id=review.location_id, status="queued")
    db.add(job)
    review.status = "pending_analysis"
    await db.commit()
    return {"status": "queued", "job_id": job.id}


@router.post("/reviews/{review_id}/draft")
async def regenerate_draft(review_id: int, db: AsyncSession = Depends(get_db)):
    """Delete existing analysis and regenerate the AI reply draft."""
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    existing_analysis = (await db.execute(
        select(ReviewAnalysis).where(ReviewAnalysis.review_id == review.id)
    )).scalar_one_or_none()
    if existing_analysis:
        await db.delete(existing_analysis)

    job = Job(job_type="analyze_review", review_id=review.id,
              location_id=review.location_id, status="queued")
    db.add(job)
    await db.commit()
    return {"status": "queued", "job_id": job.id, "note": "previous_analysis_cleared"}


@router.post("/reviews/{review_id}/approve")
async def approve_reply(
    review_id: int,
    body: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
):
    """Approve the pending reply and queue it for posting to Google."""
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (await db.execute(
        select(Reply).where(Reply.review_id == review.id)
    )).scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "No reply found for this review")

    custom_text = body.get("reply_text", "").strip()
    if custom_text:
        reply.ai_reply_text = custom_text

    reply.status = "approved"
    review.status = "approved"

    job = Job(job_type="post_reply", review_id=review.id,
              location_id=review.location_id, status="queued",
              payload={"reply_id": reply.id})
    db.add(job)
    db.add(ReviewAction(
        review_id=review.id, action_type="approved", action_status="success",
        action_payload_json={"reply_id": reply.id, "custom_text": bool(custom_text)},
        performed_by="manager",
    ))
    await db.commit()
    return {"status": "approved_and_queued", "job_id": job.id}


@router.post("/reviews/{review_id}/reply")
async def mark_manually_replied(review_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a review as manually replied (no auto-post needed)."""
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    review.status = "manually_replied"
    db.add(ReviewAction(review_id=review.id, action_type="manually_replied",
                        action_status="success", performed_by="manager"))
    await db.commit()
    return {"status": "marked_manually_replied"}


@router.post("/reviews/{review_id}/escalate")
async def escalate_review(review_id: int, db: AsyncSession = Depends(get_db)):
    """Manually escalate a review to management."""
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    review.status = "escalated"
    review.urgency = "high"
    db.add(ReviewAction(review_id=review.id, action_type="escalated",
                        action_status="success",
                        action_payload_json={"reason": "manually_escalated"},
                        performed_by="manager"))
    await db.commit()
    return {"status": "escalated"}


@router.post("/reviews/{review_id}/ignore")
async def ignore_review(review_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a review as ignored (no action needed)."""
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    review.status = "ignored"
    db.add(ReviewAction(review_id=review.id, action_type="ignored",
                        action_status="success", performed_by="manager"))
    await db.commit()
    return {"status": "ignored"}


# ── Locations ─────────────────────────────────────────────────────────────────

@router.get("/locations")
async def list_locations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Location).order_by(Location.name))
    return [{
        "id": loc.id, "slug": loc.slug, "name": loc.name,
        "address": loc.address, "city": loc.city, "state": loc.state,
        "is_active": loc.is_active,
        "fetch_google": loc.fetch_google, "fetch_yelp": loc.fetch_yelp,
        "google_location_id": loc.google_location_id, "yelp_url": loc.yelp_url,
    } for loc in result.scalars().all()]


# ── Review Settings ───────────────────────────────────────────────────────────

@router.get("/review-settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ReviewSettings).where(ReviewSettings.active == True)  # noqa: E712
    )
    return [_serialize_setting(s) for s in result.scalars().all()]


@router.put("/review-settings/{store_id}")
async def update_settings(
    store_id: str,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    platform = body.get("platform", "google")
    setting = (await db.execute(
        select(ReviewSettings).where(
            ReviewSettings.store_id == store_id,
            ReviewSettings.platform == platform,
        )
    )).scalar_one_or_none()

    if not setting:
        setting = ReviewSettings(store_id=store_id, platform=platform)
        db.add(setting)

    for field in ["auto_reply_google_positive", "email_alert_enabled",
                  "manager_email", "brand_tone", "signature_text", "active"]:
        if field in body:
            setattr(setting, field, body[field])

    await db.commit()
    await db.refresh(setting)
    return _serialize_setting(setting)


@router.post("/review-settings/seed")
async def seed_settings(db: AsyncSession = Depends(get_db)):
    """Seed default ReviewSettings rows for all active locations."""
    locations = (await db.execute(
        select(Location).where(Location.is_active == True)  # noqa: E712
    )).scalars().all()

    created = 0
    for loc in locations:
        for platform in ["google", "yelp"]:
            existing = (await db.execute(
                select(ReviewSettings).where(
                    ReviewSettings.store_id == loc.slug,
                    ReviewSettings.platform == platform,
                )
            )).scalar_one_or_none()
            if not existing:
                db.add(ReviewSettings(
                    store_id=loc.slug,
                    platform=platform,
                    auto_reply_google_positive=False,
                    email_alert_enabled=True,
                    manager_email=settings.alert_email_to or None,
                ))
                created += 1

    await db.commit()
    return {"created": created, "locations": len(locations)}


def _serialize_setting(s: ReviewSettings) -> dict:
    return {
        "id": s.id,
        "store_id": s.store_id,
        "platform": s.platform,
        "auto_reply_google_positive": s.auto_reply_google_positive,
        "email_alert_enabled": s.email_alert_enabled,
        "manager_email": s.manager_email,
        "brand_tone": s.brand_tone,
        "signature_text": s.signature_text,
        "active": s.active,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


# ── Jobs ──────────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(
    status: str | None = None,
    job_type: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    query = select(Job).order_by(desc(Job.queued_at)).limit(limit)
    if status:
        query = query.where(Job.status == status)
    if job_type:
        query = query.where(Job.job_type == job_type)

    jobs = (await db.execute(query)).scalars().all()
    return [{
        "id": j.id, "type": j.job_type, "status": j.status,
        "review_id": j.review_id, "location_id": j.location_id,
        "retry_count": j.retry_count, "max_retries": j.max_retries,
        "queued_at": j.queued_at.isoformat() if j.queued_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "error": j.error_message,
        "result": j.result,
    } for j in jobs]
