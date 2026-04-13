"""Scheduled worker: fetch reviews through provider-based sources."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models import AuthSession, EmailAlert, FetchLog, Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.providers import ProviderAuthRequiredError, ProviderFetchError, get_provider

logger = logging.getLogger("review_system.fetch_worker")


async def fetch_all_reviews(
    *,
    location_id: int | None = None,
    platform: str | None = None,
    source_id: int | None = None,
) -> dict[str, int]:
    """Iterate active sources and fetch reviews using provider implementations."""
    logger.info("=== Fetch cycle started ===")

    async with AsyncSessionLocal() as session:
        query = select(ReviewSource).where(ReviewSource.is_active.is_(True))
        if location_id:
            query = query.where(ReviewSource.location_id == location_id)
        if platform:
            query = query.where(ReviewSource.platform == platform)
        if source_id:
            query = query.where(ReviewSource.id == source_id)

        sources = (await session.execute(query.order_by(ReviewSource.location_id, ReviewSource.platform))).scalars().all()

    processed = 0
    failed = 0
    for source in sources:
        success = await _fetch_source(source.id)
        processed += 1
        if not success:
            failed += 1

    logger.info("=== Fetch cycle complete ===")
    return {"sources_processed": processed, "sources_failed": failed}


async def _fetch_source(source_id: int) -> bool:
    start = time.time()
    reviews_found = 0
    new_reviews = 0
    error_message = None

    async with AsyncSessionLocal() as session:
        source = await session.get(ReviewSource, source_id)
        location = await session.get(Location, source.location_id) if source else None
        auth_session = await _latest_auth_session(session, source.id) if source else None
        if not source or not location:
            return False

    try:
        provider = get_provider(source, auth_session=auth_session)
        session_ok, session_status = await provider.validate_session()

        async with AsyncSessionLocal() as session:
            db_source = await session.get(ReviewSource, source_id)
            if db_source:
                db_source.session_status = session_status
                if session_ok:
                    db_source.last_auth_at = datetime.utcnow()
                else:
                    db_source.last_failed_sync_at = datetime.utcnow()
            await session.commit()

        if not session_ok:
            raise ProviderAuthRequiredError(
                f"Session validation failed for {source.platform} source",
                details={"source_id": source.id},
            )

        reviews = await provider.fetch_reviews()
        reviews_found = len(reviews)
        logger.info("[%s] %s: fetched %s reviews", source.platform, location.name, reviews_found)

        async with AsyncSessionLocal() as session:
            new_reviews = await _upsert_reviews(session, source, reviews)
            await _enqueue_new_review_jobs(session, source, reviews)
            db_source = await session.get(ReviewSource, source_id)
            if db_source:
                db_source.session_status = "active"
                db_source.last_successful_sync_at = datetime.utcnow()
                db_source.last_error_message = None
            await session.commit()
        return True

    except ProviderAuthRequiredError as exc:
        error_message = str(exc)
        logger.warning("[%s] %s: auth required - %s", source.platform, location.name, exc)
        async with AsyncSessionLocal() as session:
            db_source = await session.get(ReviewSource, source_id)
            if db_source:
                db_source.session_status = "reauth_required"
                db_source.last_failed_sync_at = datetime.utcnow()
                db_source.last_error_message = error_message
            await session.commit()
        return False
    except ProviderFetchError as exc:
        error_message = str(exc)
        logger.error("[%s] %s: fetch failed - %s", source.platform, location.name, exc)
        async with AsyncSessionLocal() as session:
            db_source = await session.get(ReviewSource, source_id)
            if db_source:
                db_source.session_status = "failed"
                db_source.last_failed_sync_at = datetime.utcnow()
                db_source.last_error_message = error_message
            await session.commit()
        return False
    except Exception as exc:
        error_message = str(exc)
        logger.error("[%s] %s: unexpected fetch failure - %s", source.platform, location.name, exc)
        async with AsyncSessionLocal() as session:
            db_source = await session.get(ReviewSource, source_id)
            if db_source:
                db_source.session_status = "failed"
                db_source.last_failed_sync_at = datetime.utcnow()
                db_source.last_error_message = error_message
            await session.commit()
        return False
    finally:
        duration_ms = int((time.time() - start) * 1000)
        async with AsyncSessionLocal() as session:
            session.add(
                FetchLog(
                    location_id=source.location_id,
                    platform=source.platform,
                    reviews_found=reviews_found,
                    new_reviews=new_reviews,
                    errors=error_message,
                    duration_ms=duration_ms,
                )
            )
            await session.commit()


async def _latest_auth_session(session, source_id: int) -> AuthSession | None:
    return (
        await session.execute(
            select(AuthSession)
            .where(AuthSession.source_id == source_id)
            .order_by(AuthSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _upsert_reviews(session, source: ReviewSource, reviews) -> int:
    if not reviews:
        return 0

    await _purge_legacy_placeholder_reviews(session, source)

    external_ids = [review.external_review_id for review in reviews]
    existing_ids = set(
        (
            await session.execute(
                select(Review.external_review_id).where(
                    and_(
                        Review.platform == source.platform,
                        Review.location_id == source.location_id,
                        Review.external_review_id.in_(external_ids),
                    )
                )
            )
        ).scalars()
    )

    now = datetime.utcnow()
    for provider_review in reviews:
        payload = provider_review.raw_payload or {}
        stmt = pg_insert(Review).values(
            platform=source.platform,
            platform_review_id=provider_review.external_review_id,
            external_review_id=provider_review.external_review_id,
            location_id=source.location_id,
            source_id=source.id,
            source_url=provider_review.source_url or source.source_url,
            reviewer_name=provider_review.reviewer_name,
            rating=provider_review.rating,
            review_text=provider_review.review_text,
            review_date=provider_review.review_date,
            has_existing_reply=provider_review.has_owner_reply,
            detected_owner_reply_text=provider_review.detected_owner_reply_text,
            detected_owner_reply_at=provider_review.detected_owner_reply_at,
            has_owner_reply=provider_review.has_owner_reply,
            raw_data=payload,
            raw_payload=payload,
            collected_at=now,
            first_seen_at=now,
            last_seen_at=now,
            fetched_at=now,
        ).on_conflict_do_update(
            constraint="uq_review_platform_external_id",
            set_={
                "source_id": source.id,
                "source_url": provider_review.source_url or source.source_url,
                "reviewer_name": provider_review.reviewer_name,
                "rating": provider_review.rating,
                "review_text": provider_review.review_text,
                "review_date": provider_review.review_date,
                "has_existing_reply": provider_review.has_owner_reply,
                "detected_owner_reply_text": provider_review.detected_owner_reply_text,
                "detected_owner_reply_at": provider_review.detected_owner_reply_at,
                "has_owner_reply": provider_review.has_owner_reply,
                "raw_data": payload,
                "raw_payload": payload,
                "collected_at": now,
                "last_seen_at": now,
                "fetched_at": now,
            },
        )
        await session.execute(stmt)

    return len([review for review in reviews if review.external_review_id not in existing_ids])


async def _purge_legacy_placeholder_reviews(session, source: ReviewSource) -> None:
    if source.platform != "google":
        return

    placeholder_ids = (
        await session.execute(
            select(Review.id).where(
                and_(
                    Review.source_id == source.id,
                    Review.platform == "google",
                    Review.external_review_id.like("google-%"),
                    Review.rating == 0,
                    Review.review_date.is_(None),
                    or_(Review.reviewer_name == "Anonymous", Review.reviewer_name.is_(None)),
                )
            )
        )
    ).scalars().all()

    if not placeholder_ids:
        return

    await session.execute(delete(EmailAlert).where(EmailAlert.review_id.in_(placeholder_ids)))
    await session.execute(delete(Job).where(Job.review_id.in_(placeholder_ids)))
    await session.execute(delete(ReplySuggestion).where(ReplySuggestion.review_id.in_(placeholder_ids)))
    await session.execute(delete(Reply).where(Reply.review_id.in_(placeholder_ids)))
    await session.execute(delete(Review).where(Review.id.in_(placeholder_ids)))


async def _enqueue_new_review_jobs(session, source: ReviewSource, reviews) -> None:
    if not reviews:
        return

    ids_to_queue = [review.external_review_id for review in reviews if not review.has_owner_reply]
    if not ids_to_queue:
        return

    query = (
        select(Review)
        .where(
            and_(
                Review.platform == source.platform,
                Review.location_id == source.location_id,
                Review.external_review_id.in_(ids_to_queue),
            )
        )
        .order_by(Review.review_date.desc().nullslast(), Review.id.desc())
    )
    db_reviews = (await session.execute(query)).scalars().all()
    for review in db_reviews:
        existing_reply = (
            await session.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        queued_job = (
            await session.execute(
                select(Job).where(
                    and_(
                        Job.review_id == review.id,
                        Job.job_type == "generate_reply",
                        Job.status.in_(["queued", "processing"]),
                    )
                )
            )
        ).scalar_one_or_none()
        if review.has_owner_reply or existing_reply or queued_job:
            continue
        session.add(
            Job(
                job_type="generate_reply",
                review_id=review.id,
                location_id=review.location_id,
                source_id=source.id,
                status="queued",
                payload={"tone_mode": "gentle_professional"},
            )
        )
