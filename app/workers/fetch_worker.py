"""
Fetch Worker
============
Scheduled worker that fetches reviews from Google Business Profile and Yelp.
Each new review is stored with status="new" and an analyze_review job is enqueued.
Consecutive fetch failures trigger an admin alert email after the configured threshold.
"""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models import Location, Review, FetchLog, Job, ReviewAction
from app.services.google_auth import get_access_token
from app.services.google_reviews import list_reviews
from app.services.ai_reply import normalize_rating
from app.config import settings

logger = logging.getLogger("review_system.fetch_worker")

STAR_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


async def fetch_all_reviews():
    """Main fetch cycle: iterate all active locations, fetch Google + Yelp reviews."""
    logger.info("=== Fetch cycle started ===")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Location).where(Location.is_active == True)  # noqa: E712
        )
        locations = result.scalars().all()

    for loc in locations:
        if loc.fetch_google and loc.google_location_id:
            await _fetch_google(loc)
        if loc.fetch_yelp and loc.yelp_url:
            await _fetch_yelp(loc)

    logger.info("=== Fetch cycle complete ===")


# ── Google fetch ─────────────────────────────────────────────────────────────

async def _fetch_google(loc: Location):
    start = time.time()
    new_count = 0
    error_msg = None
    reviews = []

    try:
        token = await get_access_token(
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_refresh_token,
        )
        account_id = loc.google_account_id or settings.google_account_id
        reviews = await list_reviews(token, account_id, loc.google_location_id)
        logger.info(f"[Google] {loc.name}: fetched {len(reviews)} reviews")

        async with AsyncSessionLocal() as session:
            for r in reviews:
                review_id = r.get("reviewId", r.get("name", "").split("/")[-1])
                if not review_id:
                    continue

                raw_rating = r.get("starRating", "UNKNOWN")
                rating = STAR_MAP.get(raw_rating, 0)
                reviewer_name = r.get("reviewer", {}).get("displayName", "Anonymous")
                comment = (r.get("comment") or "").strip()
                has_reply = r.get("reviewReply") is not None
                existing_reply_text = (r.get("reviewReply") or {}).get("comment") if has_reply else None
                review_url = r.get("reviewUrl") or ""

                review_date = None
                review_date_str = r.get("createTime")
                if review_date_str:
                    try:
                        review_date = datetime.fromisoformat(review_date_str.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

                stmt = pg_insert(Review).values(
                    platform="google",
                    platform_review_id=review_id,
                    location_id=loc.id,
                    reviewer_name=reviewer_name,
                    rating=rating,
                    review_text=comment,
                    review_url=review_url,
                    review_date=review_date,
                    has_existing_reply=has_reply,
                    existing_reply_text=existing_reply_text,
                    raw_data=r,
                    status="new",
                ).on_conflict_do_update(
                    constraint="uq_review_platform_id",
                    set_={
                        # Refresh reply status if it changed on the platform
                        "has_existing_reply": has_reply,
                        "existing_reply_text": existing_reply_text,
                    },
                )

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    new_count += 1

            await session.commit()
            if new_count > 0:
                await _enqueue_analyze_jobs(session, loc, "google")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Google] {loc.name}: fetch failed — {e}")
        await _check_and_alert_fetch_failure(loc, "google", str(e))

    duration_ms = int((time.time() - start) * 1000)
    async with AsyncSessionLocal() as session:
        session.add(FetchLog(
            location_id=loc.id,
            platform="google",
            reviews_found=len(reviews),
            new_reviews=new_count,
            errors=error_msg,
            duration_ms=duration_ms,
        ))
        await session.commit()

    if new_count > 0:
        logger.info(f"[Google] {loc.name}: {new_count} new reviews saved")


# ── Yelp fetch ────────────────────────────────────────────────────────────────

async def _fetch_yelp(loc: Location):
    start = time.time()
    new_count = 0
    error_msg = None
    reviews_found = 0
    scraped = []

    try:
        from app.services.yelp_scraper import scrape_yelp_reviews
        scraped, stats = await scrape_yelp_reviews(
            url=loc.yelp_url,
            max_reviews=20,
            business_name=loc.name,
            location_name=f"{loc.city}, {loc.state}" if loc.city else "",
        )
        reviews_found = len(scraped)
        logger.info(f"[Yelp] {loc.name}: scraped {reviews_found} reviews")

        async with AsyncSessionLocal() as session:
            for r in scraped:
                review_id = r.get("id", r.get("review_id", ""))
                if not review_id:
                    continue

                rating = normalize_rating(r.get("rating", 0))

                stmt = pg_insert(Review).values(
                    platform="yelp",
                    platform_review_id=str(review_id),
                    location_id=loc.id,
                    reviewer_name=r.get("reviewer_name", "Anonymous"),
                    rating=rating,
                    review_text=r.get("text", ""),
                    review_date=None,
                    has_existing_reply=False,
                    raw_data=r,
                    status="new",
                ).on_conflict_do_nothing(constraint="uq_review_platform_id")

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    new_count += 1

            await session.commit()
            if new_count > 0:
                await _enqueue_analyze_jobs(session, loc, "yelp")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Yelp] {loc.name}: fetch failed — {e}")
        await _check_and_alert_fetch_failure(loc, "yelp", str(e))

    duration_ms = int((time.time() - start) * 1000)
    async with AsyncSessionLocal() as session:
        session.add(FetchLog(
            location_id=loc.id,
            platform="yelp",
            reviews_found=reviews_found,
            new_reviews=new_count,
            errors=error_msg,
            duration_ms=duration_ms,
        ))
        await session.commit()

    if new_count > 0:
        logger.info(f"[Yelp] {loc.name}: {new_count} new reviews saved")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _enqueue_analyze_jobs(session, loc: Location, platform: str):
    """Create analyze_review jobs for new reviews without an existing job."""
    from sqlalchemy import and_

    result = await session.execute(
        select(Review).where(
            and_(
                Review.location_id == loc.id,
                Review.platform == platform,
                Review.status == "new",
                Review.has_existing_reply == False,  # noqa: E712
                ~Review.id.in_(
                    select(Job.review_id).where(
                        Job.job_type == "analyze_review",
                        Job.status.in_(["queued", "processing"]),
                    )
                ),
            )
        )
    )
    new_reviews = result.scalars().all()

    for review in new_reviews:
        session.add(Job(
            job_type="analyze_review",
            review_id=review.id,
            location_id=loc.id,
            status="queued",
        ))
        session.add(ReviewAction(
            review_id=review.id,
            action_type="fetched",
            action_status="success",
            action_payload_json={"platform": platform, "location": loc.name},
            performed_by="system",
        ))
        review.status = "pending_analysis"

    await session.commit()
    if new_reviews:
        logger.info(f"Enqueued {len(new_reviews)} analyze_review jobs for {loc.name} ({platform})")


async def _check_and_alert_fetch_failure(loc: Location, platform: str, error_msg: str):
    """If consecutive fetch failures exceed threshold, send an admin alert."""
    from app.services.email_alert import send_fetch_failure_alert

    if not settings.alert_email_to:
        return

    async with AsyncSessionLocal() as session:
        recent_logs = (await session.execute(
            select(FetchLog)
            .where(FetchLog.location_id == loc.id, FetchLog.platform == platform)
            .order_by(FetchLog.fetched_at.desc())
            .limit(settings.fetch_failure_alert_threshold)
        )).scalars().all()

    consecutive_failures = sum(1 for log in recent_logs if log.errors)

    if consecutive_failures >= settings.fetch_failure_alert_threshold:
        send_fetch_failure_alert(
            to_email=settings.alert_email_to,
            platform=platform,
            store=loc.name,
            error_message=error_msg,
            consecutive_failures=consecutive_failures,
            app_url=settings.app_url,
        )
