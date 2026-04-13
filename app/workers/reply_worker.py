"""rq task functions for reply generation, posting, and email alerts."""

import logging
from datetime import datetime

from app.config import settings
from app.database import SyncSessionLocal
from app.models import EmailAlert, Job, Location, Reply, ReplySuggestion, Review
from app.services.ai_reply import generate_reply_bundle_sync
from app.services.email_alert import send_low_rating_alert

logger = logging.getLogger("review_system.reply_worker")


def task_generate_reply(job_id: int):
    """Generate an AI reply for a review, then route based on platform + rating."""
    session = SyncSessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = "processing"
        job.started_at = datetime.utcnow()
        session.commit()

        review = session.get(Review, job.review_id)
        location = session.get(Location, job.location_id)
        if not review or not location:
            job.status = "failed"
            job.error_message = "Review or location not found"
            session.commit()
            return

        existing = session.query(Reply).filter_by(review_id=review.id).first()
        if existing:
            job.status = "completed"
            job.result = {"reply_id": existing.id, "note": "already exists"}
            job.completed_at = datetime.utcnow()
            session.commit()
            return

        loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
        tone_mode = (job.payload or {}).get("tone_mode", settings.default_reply_tone)
        reply_bundle = generate_reply_bundle_sync(
            review_text=review.review_text or "",
            rating=review.rating,
            reviewer_name=review.reviewer_name or "Guest",
            restaurant_name=location.name,
            location=loc_str,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            tone_mode=tone_mode,
        )

        reply = Reply(
            review_id=review.id,
            ai_reply_text=reply_bundle["suggestion_text"],
            ai_model=settings.openai_model,
            tone_mode=tone_mode,
            confidence_note=reply_bundle.get("confidence_note"),
            reason_summary=reply_bundle.get("reason_summary"),
            issue_tags=reply_bundle.get("issue_tags"),
            risk_flags=reply_bundle.get("risk_flags"),
            status="pending",
            is_dry_run=settings.dry_run,
        )
        session.add(reply)
        session.flush()

        session.add(
            ReplySuggestion(
                review_id=review.id,
                tone_mode=tone_mode,
                suggestion_text=reply_bundle["suggestion_text"],
                model_name=settings.openai_model,
                sentiment=reply_bundle.get("sentiment"),
                issue_tags=reply_bundle.get("issue_tags"),
                risk_flags=reply_bundle.get("risk_flags"),
                confidence_note=reply_bundle.get("confidence_note"),
                reason_summary=reply_bundle.get("reason_summary"),
                created_by="system",
            )
        )

        if review.rating <= 3:
            session.add(
                Job(
                    job_type="send_alert_email",
                    review_id=review.id,
                    location_id=location.id,
                    source_id=job.source_id,
                    status="queued",
                    payload={"reply_id": reply.id},
                )
            )
            reply.status = "pending"
        else:
            reply.status = "suggested"

        job.status = "completed"
        job.result = {"reply_id": reply.id, "action": "generated"}
        job.completed_at = datetime.utcnow()
        session.commit()

        logger.info(
            "Reply generated for review %s (%s %s*) at %s",
            review.id,
            review.platform,
            review.rating,
            location.name,
        )

    except Exception as exc:
        logger.error("task_generate_reply failed for job %s: %s", job_id, exc)
        if "job" in locals() and job:
            job.status = "failed"
            job.error_message = str(exc)[:500]
            session.commit()
        raise
    finally:
        session.close()


def task_post_reply(job_id: int):
    """Mark an operator-assisted reply as approved."""
    session = SyncSessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            return

        job.status = "processing"
        job.started_at = datetime.utcnow()
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

        reply.status = "approved"
        reply.is_dry_run = settings.dry_run
        job.status = "completed"
        job.result = {"posted": False, "mode": "operator_assisted", "dry_run": settings.dry_run}
        job.completed_at = datetime.utcnow()
        session.commit()
        logger.info("Reply approved for review %s at %s; waiting for manual portal posting", review.id, location.name)

    except Exception as exc:
        logger.error("task_post_reply failed for job %s: %s", job_id, exc)
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
        job.started_at = datetime.utcnow()
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

        session.add(
            EmailAlert(
                review_id=review.id,
                recipient=settings.alert_email_to,
                subject=f"[{review.rating} Star] Negative Review - {location.name}",
                body=f"Review by {review.reviewer_name}: {(review.review_text or '')[:200]}",
                status="sent" if sent else "failed",
                sent_at=datetime.utcnow() if sent else None,
            )
        )

        if reply:
            reply.status = "email_sent" if sent else "pending"

        job.status = "completed" if sent else "failed"
        job.result = {"email_sent": sent}
        job.completed_at = datetime.utcnow()
        session.commit()

    except Exception as exc:
        logger.error("task_send_alert_email failed for job %s: %s", job_id, exc)
        raise
    finally:
        session.close()
