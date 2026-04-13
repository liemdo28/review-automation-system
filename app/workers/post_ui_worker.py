"""UI posting fallback worker for browser-driven reply submission."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.config import settings
from app.database import SyncSessionLocal
from app.models import Job, Location, Reply, Review, ReviewSource
from app.providers import ProviderAuthRequiredError, ProviderPostError, get_provider
from app.services.session_resolution import resolve_auth_session_for_source_sync

logger = logging.getLogger("review_system.post_ui_worker")


def task_post_ui_reply(job_id: int):
    """Post a prepared reply through the source UI when direct APIs are unavailable."""
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
        source = session.get(ReviewSource, review.source_id) if review and review.source_id else None

        if not reply or not review or not location or not source:
            job.status = "failed"
            job.error_message = "Missing reply, review, location, or source"
            session.commit()
            return

        review.workflow_status = "posting_in_ui"
        reply.status = "processing"
        session.commit()

        if settings.dry_run:
            job.status = "failed"
            job.error_message = "DRY_RUN is enabled. Turn it off before live UI posting."
            reply.status = "failed"
            reply.last_auto_post_error = job.error_message
            reply.auto_post_attempts = (reply.auto_post_attempts or 0) + 1
            review.workflow_status = "manual_review_required"
            session.commit()
            return

        if not reply.ai_reply_text or not reply.ai_reply_text.strip():
            job.status = "failed"
            job.error_message = "Prepared reply text is empty"
            reply.status = "failed"
            reply.last_auto_post_error = job.error_message
            review.workflow_status = "auto_post_failed"
            session.commit()
            return

        if review.has_owner_reply or reply.status == "posted":
            now = datetime.utcnow()
            reply.status = "posted"
            reply.posted_at = reply.posted_at or now
            reply.last_auto_post_at = reply.last_auto_post_at or reply.posted_at
            reply.posted_by_mode = "auto"
            review.workflow_status = "posted"
            review.posted_by_mode = "auto"
            review.has_owner_reply = True
            job.status = "completed"
            job.result = {"posted": True, "mode": "ui_fallback", "already_replied": True}
            job.completed_at = now
            session.commit()
            return

        auth_session = resolve_auth_session_for_source_sync(session, source, location=location)
        setattr(source, "expected_store_name", location.name)
        provider = get_provider(source, auth_session=auth_session)

        try:
            result = asyncio.run(provider.post_reply(review, reply.ai_reply_text))
        except ProviderAuthRequiredError as exc:
            source.session_status = "reauth_required"
            source.last_failed_sync_at = datetime.utcnow()
            source.last_error_message = str(exc)
            reply.status = "failed"
            reply.last_auto_post_error = str(exc)
            reply.auto_post_attempts = (reply.auto_post_attempts or 0) + 1
            review.workflow_status = "blocked_auth"
            job.status = "failed"
            job.error_message = str(exc)
            job.result = {"mode": "ui_fallback", **(exc.details or {})}
            job.completed_at = datetime.utcnow()
            session.commit()
            return
        except ProviderPostError as exc:
            reply.status = "failed"
            reply.last_auto_post_error = str(exc)
            reply.auto_post_attempts = (reply.auto_post_attempts or 0) + 1
            review.workflow_status = "post_verification_required" if (exc.details or {}).get("verification_required") else "auto_post_failed"
            job.status = "failed"
            job.error_message = str(exc)
            job.result = {"mode": "ui_fallback", **(exc.details or {})}
            job.completed_at = datetime.utcnow()
            session.commit()
            return

        now = datetime.utcnow()
        reply.status = "posted"
        reply.is_dry_run = False
        reply.posted_by_mode = "auto"
        reply.posted_at = now
        reply.last_auto_post_at = now
        reply.last_auto_post_error = None
        reply.auto_post_attempts = (reply.auto_post_attempts or 0) + 1
        review.workflow_status = "posted"
        review.posted_by_mode = "auto"
        review.has_owner_reply = True
        review.detected_owner_reply_text = reply.ai_reply_text
        review.detected_owner_reply_at = now
        source.session_status = "active"
        source.last_successful_sync_at = now
        source.last_error_message = None
        job.status = "completed"
        job.result = {"posted": True, "mode": "ui_fallback", **(result or {})}
        job.completed_at = now
        session.commit()

        logger.info("UI fallback posted review %s for %s", review.id, location.name)

    except Exception as exc:
        logger.error("task_post_ui_reply failed for job %s: %s", job_id, exc)
        if "job" in locals() and job:
            job.status = "failed"
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.utcnow()
            session.commit()
        raise
    finally:
        session.close()
