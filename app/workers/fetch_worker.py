"""Scheduled worker: fetch reviews from Google + Yelp every 10 minutes."""
import logging
import time
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models import Location, Review, FetchLog, Job
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


async def _fetch_google(loc: Location):
    start = time.time()
    new_count = 0
    error_msg = None

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
                review_date_str = r.get("createTime")
                review_date = None
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
                    review_date=review_date,
                    has_existing_reply=has_reply,
                    raw_data=r,
                ).on_conflict_do_nothing(constraint="uq_review_platform_id")

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    new_count += 1

            await session.commit()

            # Enqueue jobs for new reviews that don't already have replies
            if new_count > 0:
                await _enqueue_new_review_jobs(session, loc, "google")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Google] {loc.name}: fetch failed - {e}")

    duration_ms = int((time.time() - start) * 1000)

    async with AsyncSessionLocal() as session:
        session.add(FetchLog(
            location_id=loc.id,
            platform="google",
            reviews_found=len(reviews) if not error_msg else 0,
            new_reviews=new_count,
            errors=error_msg,
            duration_ms=duration_ms,
        ))
        await session.commit()

    if new_count > 0:
        logger.info(f"[Google] {loc.name}: {new_count} new reviews saved")


async def _fetch_yelp(loc: Location):
    """Fetch Yelp reviews using Playwright. Imports lazily to avoid startup cost."""
    start = time.time()
    new_count = 0
    error_msg = None
    reviews_found = 0

    try:
        from app.services.yelp_scraper import scrape_yelp_reviews
        reviews, stats = await scrape_yelp_reviews(
            url=loc.yelp_url,
            max_reviews=20,
            business_name=loc.name,
            location_name=f"{loc.city}, {loc.state}" if loc.city else "",
        )
        reviews_found = len(reviews)
        logger.info(f"[Yelp] {loc.name}: scraped {reviews_found} reviews")

        async with AsyncSessionLocal() as session:
            for r in reviews:
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
                ).on_conflict_do_nothing(constraint="uq_review_platform_id")

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    new_count += 1

            await session.commit()

            if new_count > 0:
                await _enqueue_new_review_jobs(session, loc, "yelp")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Yelp] {loc.name}: fetch failed - {e}")

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


async def _enqueue_new_review_jobs(session, loc: Location, platform: str):
    """Create generate_reply jobs for new reviews without existing replies."""
    from sqlalchemy import and_
    from app.models import Reply

    result = await session.execute(
        select(Review).where(
            and_(
                Review.location_id == loc.id,
                Review.platform == platform,
                Review.has_existing_reply == False,  # noqa: E712
                ~Review.id.in_(select(Reply.review_id)),
                ~Review.id.in_(select(Job.review_id).where(Job.job_type == "generate_reply")),
            )
        )
    )
    new_reviews = result.scalars().all()

    for review in new_reviews:
        session.add(Job(
            job_type="generate_reply",
            review_id=review.id,
            location_id=loc.id,
            status="queued",
        ))

    await session.commit()
    if new_reviews:
        logger.info(f"Enqueued {len(new_reviews)} generate_reply jobs for {loc.name} ({platform})")
