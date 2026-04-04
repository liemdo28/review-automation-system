"""rq task functions for reply generation, posting, and email alerts."""
import logging
from datetime import datetime, timezone

from app.database import SyncSessionLocal
from app.models import Review, Reply, Job, Location, EmailAlert
from app.services.ai_reply import generate_reply_sync
from app.services.google_auth import get_access_token_sync
from app.services.google_reviews import reply_to_review_sync
from app.services.email_alert import send_low_rating_alert
from app.config import settings

logger = logging.getLogger("review_system.reply_worker")


def task_generate_reply(job_id: int):
    """Generate an AI reply for a review, then route based on platform + rating."""
    session = SyncSessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        session.commit()

        review = session.get(Review, job.review_id)
        location = session.get(Location, job.location_id)
        if not review or not location:
            job.status = "failed"
            job.error_message = "Review or location not found"
            session.commit()
            return

        # Check if reply already exists (idempotency)
        existing = session.query(Reply).filter_by(review_id=review.id).first()
        if existing:
            job.status = "completed"
            job.result = {"reply_id": existing.id, "note": "already exists"}
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            return

        # Generate AI reply
        loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
        reply_text = generate_reply_sync(
            review_text=review.review_text or "",
            rating=review.rating,
            reviewer_name=review.reviewer_name or "Guest",
            restaurant_name=location.name,
            location=loc_str,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )

        # Save reply
        reply = Reply(
            review_id=review.id,
            ai_reply_text=reply_text,
            ai_model=settings.openai_model,
            status="pending",
            is_dry_run=settings.dry_run,
        )
        session.add(reply)
        session.flush()

        # Route based on platform + rating
        if review.platform == "google" and review.rating >= 4:
            # Auto-post for positive Google reviews
            next_job = Job(
                job_type="post_reply",
                review_id=review.id,
                location_id=location.id,
                status="queued",
                payload={"reply_id": reply.id},
            )
            session.add(next_job)
        elif review.platform == "google" and review.rating <= 3:
            # Email alert for negative Google reviews
            next_job = Job(
                job_type="send_alert_email",
                review_id=review.id,
                location_id=location.id,
                status="queued",
                payload={"reply_id": reply.id},
            )
            session.add(next_job)
        else:
            # Yelp: suggest only, mark as approved (viewable on dashboard)
            reply.status = "suggested"

        job.status = "completed"
        job.result = {"reply_id": reply.id, "action": "generated"}
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(
            f"Reply generated for review {review.id} "
            f"({review.platform} {review.rating}*) at {location.name}"
        )

    except Exception as e:
        logger.error(f"task_generate_reply failed for job {job_id}: {e}")
        if job:
            job.status = "failed"
            job.error_message = str(e)[:500]
            session.commit()
        raise
    finally:
        session.close()


def task_post_reply(job_id: int):
    """Post an AI reply to Google Business Profile."""
    session = SyncSessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            return

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        session.commit()

        reply_id = (job.payload or {}).get("reply_id")
        reply = session.get(Reply, reply_id) if reply_id else None
        review = session.get(Review, job.review_id)
        location = session.get(Location, job.location_id)

        if not reply or not review or not location:
            job.status = "failed"
            job.error_message = "Missing reply, review, or location"
            session.commit()
            return

        if settings.dry_run:
            reply.status = "posted"
            reply.is_dry_run = True
            reply.posted_at = datetime.now(timezone.utc)
            job.status = "completed"
            job.result = {"dry_run": True}
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(f"[DRY RUN] Reply for review {review.id} marked as posted")
            return

        # Post to Google
        try:
            token = get_access_token_sync(
                settings.google_client_id,
                settings.google_client_secret,
                settings.google_refresh_token,
            )
            account_id = location.google_account_id or settings.google_account_id
            reply_to_review_sync(
                token, account_id, location.google_location_id,
                review.platform_review_id, reply.ai_reply_text,
            )

            reply.status = "posted"
            reply.posted_at = datetime.now(timezone.utc)
            job.status = "completed"
            job.result = {"posted": True}
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(f"Reply posted for review {review.id} at {location.name}")

        except Exception as e:
            job.retry_count += 1
            if job.retry_count >= job.max_retries:
                job.status = "failed"
                reply.status = "failed"
                reply.error_message = str(e)[:500]
            else:
                job.status = "queued"  # Will be re-processed
            job.error_message = str(e)[:500]
            session.commit()
            logger.error(f"Post reply failed (attempt {job.retry_count}): {e}")

    except Exception as e:
        logger.error(f"task_post_reply failed for job {job_id}: {e}")
        raise
    finally:
        session.close()


def task_send_alert_email(job_id: int):
    """Send email alert for a negative review."""
    session = SyncSessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            return

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        session.commit()

        reply_id = (job.payload or {}).get("reply_id")
        reply = session.get(Reply, reply_id) if reply_id else None
        review = session.get(Review, job.review_id)
        location = session.get(Location, job.location_id)

        if not review or not location:
            job.status = "failed"
            job.error_message = "Missing review or location"
            session.commit()
            return

        loc_str = f"{location.city}, {location.state}" if location.city else ""
        suggested = reply.ai_reply_text if reply else ""

        sent = send_low_rating_alert(
            reviewer_name=review.reviewer_name or "Anonymous",
            rating=review.rating,
            review_text=review.review_text or "",
            suggested_reply=suggested,
            restaurant_name=location.name,
            location=loc_str,
            review_id=review.id,
        )

        # Record alert
        alert = EmailAlert(
            review_id=review.id,
            recipient=settings.alert_email_to,
            subject=f"[{review.rating} Star] Negative Review - {location.name}",
            body=f"Review by {review.reviewer_name}: {(review.review_text or '')[:200]}",
            status="sent" if sent else "failed",
            sent_at=datetime.now(timezone.utc) if sent else None,
        )
        session.add(alert)

        if reply:
            reply.status = "email_sent" if sent else "pending"

        job.status = "completed" if sent else "failed"
        job.result = {"email_sent": sent}
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

    except Exception as e:
        logger.error(f"task_send_alert_email failed for job {job_id}: {e}")
        raise
    finally:
        session.close()
