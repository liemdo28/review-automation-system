"""rq task functions for reply generation, posting, and email alerts."""

import logging
from datetime import datetime

from app.config import settings
from app.database import SyncSessionLocal
from app.models import EmailAlert, Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.auto_reply_policy import (
    count_auto_posts_today_sync,
    evaluate_auto_reply,
    latest_suggestion_for_review_sync,
    load_effective_auto_reply_config_sync,
)
from app.services.ai_reply import generate_reply_bundle_sync, sanitize_review_signals
from app.services.email_alert import send_low_rating_alert

logger = logging.getLogger("review_system.reply_worker")


def _apply_review_audit_sync(review: Review, bundle: dict) -> None:
    is_flagged = bool(review.rating <= 3)
    review.is_flagged = is_flagged
    review.issue_category = bundle.get("issue_category")
    review.severity_level = bundle.get("severity_level")
    review.analysis_summary = bundle.get("analysis_summary")
    if not is_flagged:
        review.gm_report_sent = False


def task_generate_reply(job_id: int):
    """Generate an AI reply and queue deterministic auto-reply evaluation."""
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
        _apply_review_audit_sync(review, reply_bundle)

        reply = Reply(
            review_id=review.id,
            ai_reply_text=reply_bundle["suggestion_text"],
            ai_model=settings.openai_model,
            tone_mode=tone_mode,
            confidence_note=reply_bundle.get("confidence_note"),
            reason_summary=reply_bundle.get("reason_summary"),
            issue_tags=reply_bundle.get("issue_tags"),
            risk_flags=reply_bundle.get("risk_flags"),
            status="suggested",
            is_dry_run=settings.dry_run,
            decision_snapshot={
                "sentiment": reply_bundle.get("sentiment"),
                "issue_category": reply_bundle.get("issue_category"),
                "severity_level": reply_bundle.get("severity_level"),
                "analysis_summary": reply_bundle.get("analysis_summary"),
            },
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

        review.workflow_status = "suggested"
        session.add(
            Job(
                job_type="review_decision",
                review_id=review.id,
                location_id=location.id,
                source_id=job.source_id,
                status="queued",
                payload={
                    "reply_id": reply.id,
                    "tone_mode": tone_mode,
                    "sentiment": reply_bundle.get("sentiment"),
                },
            )
        )

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
    """Mark a reply as approved inside START for operator-assisted manual portal posting."""
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

        post_mode = (job.payload or {}).get("mode", "operator_assisted")
        reply.status = "approved"
        reply.is_dry_run = settings.dry_run
        reply.posted_by_mode = post_mode
        review.workflow_status = "approved"
        review.posted_by_mode = post_mode
        job.status = "completed"
        job.result = {"posted": False, "mode": post_mode, "dry_run": settings.dry_run}
        job.completed_at = datetime.utcnow()
        session.commit()
        logger.info(
            "Reply approved in START for review %s at %s; source portal posting remains operator-assisted",
            review.id,
            location.name,
        )

    except Exception as exc:
        logger.error("task_post_reply failed for job %s: %s", job_id, exc)
        if "job" in locals() and job:
            job.status = "failed"
            job.error_message = str(exc)[:500]
            session.commit()
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


def task_review_decision(job_id: int):
    """Evaluate deterministic auto-reply policy after suggestion generation."""
    session = SyncSessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            return

        job.status = "processing"
        job.started_at = datetime.utcnow()
        session.commit()

        review = session.get(Review, job.review_id)
        location = session.get(Location, job.location_id)
        source = session.get(ReviewSource, job.source_id) if job.source_id else None
        reply_id = (job.payload or {}).get("reply_id")
        reply = session.get(Reply, reply_id) if reply_id else None

        if not review or not location or not reply:
            job.status = "failed"
            job.error_message = "Missing review, location, or reply"
            session.commit()
            return

        config = load_effective_auto_reply_config_sync(session, location=location)
        suggestion = latest_suggestion_for_review_sync(session, review.id)
        signal_bundle = sanitize_review_signals(
            review.review_text or "",
            review.rating,
            issue_tags=reply.issue_tags or (suggestion.issue_tags if suggestion else None),
            risk_flags=reply.risk_flags or (suggestion.risk_flags if suggestion else None),
            sentiment=(job.payload or {}).get("sentiment") or (suggestion.sentiment if suggestion else None),
            reason_summary=reply.reason_summary or (suggestion.reason_summary if suggestion else None),
            issue_category=review.issue_category,
            severity_level=review.severity_level,
            analysis_summary=review.analysis_summary,
            confidence_note=reply.confidence_note or (suggestion.confidence_note if suggestion else None),
        )
        reply.issue_tags = signal_bundle["issue_tags"]
        reply.risk_flags = signal_bundle["risk_flags"]
        reply.reason_summary = signal_bundle["reason_summary"]
        reply.confidence_note = signal_bundle["confidence_note"]
        review.issue_category = signal_bundle["issue_category"]
        review.severity_level = signal_bundle["severity_level"]
        review.analysis_summary = signal_bundle["analysis_summary"]
        if suggestion:
            suggestion.sentiment = signal_bundle["sentiment"]
            suggestion.issue_tags = signal_bundle["issue_tags"]
            suggestion.risk_flags = signal_bundle["risk_flags"]
            suggestion.reason_summary = signal_bundle["reason_summary"]
            suggestion.confidence_note = signal_bundle["confidence_note"]
        auto_posts_today = count_auto_posts_today_sync(session, location_id=location.id)
        decision = evaluate_auto_reply(
            review,
            source=source,
            config=config,
            suggestion_sentiment=signal_bundle["sentiment"],
            issue_tags=signal_bundle["issue_tags"],
            risk_flags=signal_bundle["risk_flags"],
            confidence_note=signal_bundle["confidence_note"],
            auto_posts_today=auto_posts_today,
        )

        review.workflow_status = decision.workflow_status
        review.auto_reply_eligible = decision.allow_auto_post
        review.auto_reply_decision_reason = decision.decision_reason
        review.auto_reply_risk_level = decision.risk_level
        review.escalated = decision.escalation_required
        review.escalation_reason = decision.escalation_reason
        review.policy_version = decision.policy_version
        review.last_auto_decision_at = datetime.utcnow()

        existing_snapshot = dict(reply.decision_snapshot or {})
        existing_snapshot.update(decision.as_dict())
        existing_snapshot["sentiment"] = signal_bundle["sentiment"]
        existing_snapshot["issue_category"] = signal_bundle["issue_category"]
        existing_snapshot["severity_level"] = signal_bundle["severity_level"]
        existing_snapshot["analysis_summary"] = signal_bundle["analysis_summary"]
        reply.decision_snapshot = existing_snapshot
        reply.tone_mode = decision.recommended_tone_mode
        reply.status = "suggested"

        if decision.escalation_required:
            escalation_job = (
                session.query(Job)
                .filter(
                    Job.review_id == review.id,
                    Job.job_type == "escalate_review",
                    Job.status.in_(["queued", "processing"]),
                )
                .first()
            )
            if not escalation_job:
                session.add(
                    Job(
                        job_type="escalate_review",
                        review_id=review.id,
                        location_id=location.id,
                        source_id=job.source_id,
                        status="queued",
                        payload={"reply_id": reply.id, "decision_reason": decision.decision_reason},
                    )
                )
        elif decision.queue_auto_post:
            auto_post_job = (
                session.query(Job)
                .filter(
                    Job.review_id == review.id,
                    Job.job_type == "post_ui_reply",
                    Job.status.in_(["queued", "processing"]),
                )
                .first()
            )
            if not auto_post_job:
                session.add(
                    Job(
                        job_type="post_ui_reply",
                        review_id=review.id,
                        location_id=location.id,
                        source_id=job.source_id,
                        status="queued",
                        payload={"reply_id": reply.id, "mode": "auto"},
                    )
                )

        job.status = "completed"
        job.result = decision.as_dict()
        job.completed_at = datetime.utcnow()
        session.commit()

    except Exception as exc:
        logger.error("task_review_decision failed for job %s: %s", job_id, exc)
        if "job" in locals() and job:
            job.status = "failed"
            job.error_message = str(exc)[:500]
            session.commit()
        raise
    finally:
        session.close()


def task_escalate_review(job_id: int):
    """Create and optionally send escalation alerts for high-risk reviews."""
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

        review.workflow_status = "escalated"
        review.escalated = True
        if not review.escalation_reason:
            review.escalation_reason = (job.payload or {}).get("decision_reason") or "Review needs manual escalation."

        loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
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

        recipients = settings.alert_email_to
        session.add(
            EmailAlert(
                review_id=review.id,
                recipient=recipients,
                subject=f"[Escalation] Review requires manual attention - {location.name}",
                body=review.escalation_reason or "Review requires manual escalation.",
                status="sent" if sent else "failed",
                sent_at=datetime.utcnow() if sent else None,
            )
        )

        if reply:
            reply.status = "suggested"

        job.status = "completed" if sent or not settings.alert_email_to else "failed"
        job.result = {"escalated": True, "email_sent": sent}
        job.completed_at = datetime.utcnow()
        session.commit()

    except Exception as exc:
        logger.error("task_escalate_review failed for job %s: %s", job_id, exc)
        if "job" in locals() and job:
            job.status = "failed"
            job.error_message = str(exc)[:500]
            session.commit()
        raise
    finally:
        session.close()
