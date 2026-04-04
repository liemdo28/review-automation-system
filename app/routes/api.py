"""REST API endpoints."""
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Location, Review, Reply, Job, FetchLog
from app.workers.fetch_worker import fetch_all_reviews

router = APIRouter(tags=["api"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(func.count()).select_from(Location))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    total_reviews = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    total_replies = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "posted")
    )).scalar() or 0
    pending = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "pending")
    )).scalar() or 0
    queued_jobs = (await db.execute(
        select(func.count()).select_from(Job).where(Job.status == "queued")
    )).scalar() or 0

    # Per-location stats
    loc_stats = []
    locations = (await db.execute(select(Location).where(Location.is_active == True))).scalars().all()  # noqa: E712
    for loc in locations:
        review_count = (await db.execute(
            select(func.count()).select_from(Review).where(Review.location_id == loc.id)
        )).scalar() or 0
        reply_count = (await db.execute(
            select(func.count()).select_from(Reply).where(
                and_(Reply.status == "posted", Reply.review_id.in_(
                    select(Review.id).where(Review.location_id == loc.id)
                ))
            )
        )).scalar() or 0
        loc_stats.append({
            "id": loc.id, "slug": loc.slug, "name": loc.name,
            "reviews": review_count, "replies": reply_count,
        })

    return {
        "total_reviews": total_reviews,
        "total_replies": total_replies,
        "pending_replies": pending,
        "queued_jobs": queued_jobs,
        "locations": loc_stats,
    }


@router.get("/reviews")
async def list_reviews(
    location_id: int | None = None,
    platform: str | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(Review).order_by(Review.fetched_at.desc())
    if location_id:
        query = query.where(Review.location_id == location_id)
    if platform:
        query = query.where(Review.platform == platform)
    if min_rating:
        query = query.where(Review.rating >= min_rating)
    if max_rating:
        query = query.where(Review.rating <= max_rating)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    reviews = result.scalars().all()

    items = []
    for r in reviews:
        reply = (await db.execute(
            select(Reply).where(Reply.review_id == r.id)
        )).scalar_one_or_none()

        items.append({
            "id": r.id,
            "platform": r.platform,
            "reviewer_name": r.reviewer_name,
            "rating": r.rating,
            "review_text": (r.review_text or "")[:200],
            "review_date": r.review_date.isoformat() if r.review_date else None,
            "location_id": r.location_id,
            "has_existing_reply": r.has_existing_reply,
            "reply_status": reply.status if reply else None,
            "reply_text": (reply.ai_reply_text[:200] if reply else None),
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        })

    return {"reviews": items, "count": len(items), "offset": offset}


@router.get("/reviews/{review_id}")
async def get_review(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (await db.execute(
        select(Reply).where(Reply.review_id == review.id)
    )).scalar_one_or_none()

    location = await db.get(Location, review.location_id)

    return {
        "id": review.id,
        "platform": review.platform,
        "platform_review_id": review.platform_review_id,
        "reviewer_name": review.reviewer_name,
        "rating": review.rating,
        "review_text": review.review_text,
        "review_date": review.review_date.isoformat() if review.review_date else None,
        "location": {"id": location.id, "name": location.name, "slug": location.slug} if location else None,
        "reply": {
            "id": reply.id,
            "text": reply.ai_reply_text,
            "status": reply.status,
            "model": reply.ai_model,
            "is_dry_run": reply.is_dry_run,
            "posted_at": reply.posted_at.isoformat() if reply.posted_at else None,
        } if reply else None,
    }


@router.post("/reviews/{review_id}/approve")
async def approve_reply(review_id: int, db: AsyncSession = Depends(get_db)):
    """Approve and post a pending reply for a negative review."""
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (await db.execute(
        select(Reply).where(Reply.review_id == review.id)
    )).scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "No reply found for this review")

    # Create a post_reply job
    job = Job(
        job_type="post_reply",
        review_id=review.id,
        location_id=review.location_id,
        status="queued",
        payload={"reply_id": reply.id},
    )
    db.add(job)
    reply.status = "approved"
    await db.commit()

    return {"status": "queued", "job_id": job.id}


@router.get("/locations")
async def list_locations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Location).order_by(Location.name))
    locations = result.scalars().all()
    return [{
        "id": l.id, "slug": l.slug, "name": l.name,
        "address": l.address, "city": l.city, "state": l.state,
        "is_active": l.is_active,
        "fetch_google": l.fetch_google, "fetch_yelp": l.fetch_yelp,
        "google_location_id": l.google_location_id,
        "yelp_url": l.yelp_url,
    } for l in locations]


@router.post("/fetch/trigger")
async def trigger_fetch():
    """Manually trigger a fetch cycle."""
    asyncio.create_task(fetch_all_reviews())
    return {"status": "fetch_triggered"}


@router.get("/jobs")
async def list_jobs(limit: int = 20, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).order_by(Job.queued_at.desc()).limit(limit)
    )
    jobs = result.scalars().all()
    return [{
        "id": j.id, "type": j.job_type, "status": j.status,
        "review_id": j.review_id,
        "retry_count": j.retry_count,
        "queued_at": j.queued_at.isoformat() if j.queued_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "error": j.error_message,
    } for j in jobs]
