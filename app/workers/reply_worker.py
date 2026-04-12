"""
Reply Worker — Full Pipeline
=============================
rq task functions that implement the complete review processing pipeline:

  task_analyze_review   → AI analysis + rule engine + routing
  task_post_reply       → Post approved reply to Google
  task_send_alert_email → Send manager alert email
  task_generate_reply   → Legacy shim (redirects to analyze)

Every decision is logged to review_actions for full auditability.
The rule engine is ALWAYS the final authority — the LLM cannot override it.
"""
import logging
from datetime import datetime, timezone

from app.database import SyncSessionLocal
from app.models import (
    Review, Reply, Job, Location,
    EmailAlert, ReviewAnalysis, ReviewAction, ReviewSettings,
)
from app.services.ai_analysis import analyze_review_sync, PROMPT_VERSION
from app.services.rule_engine import evaluate as rule_evaluate
from app.services.google_auth import get_access_token_sync
from app.services.google_reviews import reply_to_review_sync
from app.services.email_alert import send_review_alert, send_publish_failure_alert
from app.config import settings

logger = logging.getLogger("review_system.reply_worker")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_action(session, review_id: int, action_type: str, status: str = "success",
                payload: dict = None, error: str = None, by: str = "system"):
    session.add(ReviewAction(
        review_id=review_id,
        action_type=action_type,
        action_status=status,
        action_payload_json=payload,
        error_message=error,
        performed_by=by,
    ))


def _get_auto_reply_setting(session, location_slug: str) -> bool:
    """Look up per-store setting; fall back to global config."""
    setting = session.query(ReviewSettings).filter_by(
        store_id=location_slug, platform="google", active=True
    ).first()
    if setting is not None:
        return setting.auto_reply_google_positive
    return settings.auto_reply_google_positive


def _get_manager_email(session, location_slug: str) -> str:
    """Get manager email from settings or fall back to global."""
    setting = session.query(ReviewSettings).filter_by(
        store_id=location_slug, active=True
    ).first()
    if setting and setting.manager_email:
        return setting.manager_email
    return settings.alert_email_to


# ── Main analysis task ────────────────────────────────────────────────────────

def task_analyze_review(job_id: int):
    """
    Full pipeline for a new review:
    1. Run AI analysis
    2. Apply rule engine
    3. Save ReviewAnalysis record
    4. Update Review status fields
    5. Create Reply draft
    6. Enqueue post_reply or send_alert_email as needed
    7. Log all actions to review_actions
    """
    session = SyncSessionLocal()
    job = None
    review = None
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

        # Idempotency: skip if already analyzed
        existing_analysis = session.query(ReviewAnalysis).filter_by(review_id=review.id).first()
        if existing_analysis:
            job.status = "completed"
            job.result = {"note": "already_analyzed", "analysis_id": existing_analysis.id}
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            return

        loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
        auto_reply_enabled = _get_auto_reply_setting(session, location.slug)

        # ── Step 1: AI Analysis ───────────────────────────────────────────────
        analysis_dict, raw_response = analyze_review_sync(
            review_text=review.review_text or "",
            rating=review.rating,
            reviewer_name=review.reviewer_name or "Guest",
            restaurant_name=location.name,
            location=loc_str,
            platform=review.platform,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )

        # ── Step 2: Rule Engine (overrides AI where needed) ──────────────────
        decision = rule_evaluate(
            platform=review.platform,
            rating=review.rating,
            review_text=review.review_text or "",
            ai_analysis=analysis_dict,
            auto_reply_setting_enabled=auto_reply_enabled,
        )

        # ── Step 3: Persist ReviewAnalysis ───────────────────────────────────
        ra = ReviewAnalysis(
            review_id=review.id,
            sentiment=analysis_dict["sentiment"],
            issue_types_json=analysis_dict["issue_types"],
            urgency=decision.urgency,
            reply_recommended=analysis_dict["reply_recommended"],
            auto_reply_allowed=decision.auto_reply,
            manager_attention_required=not decision.auto_reply and decision.should_send_email,
            summary=analysis_dict["summary"],
            suggested_reply=analysis_dict["suggested_reply"],
            internal_notes=decision.override_reason if decision.override_reason else None,
            model_name=settings.openai_model,
            prompt_version=PROMPT_VERSION,
            raw_ai_response_json={"raw": raw_response[:4000] if raw_response else None},
        )
        session.add(ra)
        session.flush()

        # ── Step 4: Update Review fields ─────────────────────────────────────
        review.sentiment = analysis_dict["sentiment"]
        review.urgency = decision.urgency
        review.is_sensitive = decision.is_sensitive
        review.auto_reply_allowed = decision.auto_reply
        review.manager_attention_required = decision.should_send_email
        review.issue_types_json = analysis_dict["issue_types"]
        review.status = decision.final_status

        # ── Step 5: Create Reply draft ────────────────────────────────────────
        existing_reply = session.query(Reply).filter_by(review_id=review.id).first()
        reply_id = None
        if not existing_reply and analysis_dict.get("suggested_reply"):
            new_reply = Reply(
                review_id=review.id,
                ai_reply_text=analysis_dict["suggested_reply"],
                ai_model=settings.openai_model,
                status="pending",
                is_dry_run=settings.dry_run,
            )
            session.add(new_reply)
            session.flush()
            reply_id = new_reply.id
        elif existing_reply:
            reply_id = existing_reply.id

        _log_action(session, review.id, "analyzed", payload={
            "sentiment": analysis_dict["sentiment"],
            "urgency": decision.urgency,
            "is_sensitive": decision.is_sensitive,
            "auto_reply": decision.auto_reply,
            "final_status": decision.final_status,
            "reason": decision.override_reason,
        })

        if reply_id:
            _log_action(session, review.id, "drafted", payload={"reply_id": reply_id})

        # ── Step 6: Enqueue next actions ──────────────────────────────────────
        if decision.auto_reply and reply_id and review.platform == "google":
            session.add(Job(
                job_type="post_reply",
                review_id=review.id,
                location_id=location.id,
                status="queued",
                payload={"reply_id": reply_id},
            ))

        if decision.should_send_email:
            session.add(Job(
                job_type="send_alert_email",
                review_id=review.id,
                location_id=location.id,
                status="queued",
                payload={"reply_id": reply_id},
            ))

        if decision.is_sensitive:
            _log_action(session, review.id, "escalated", payload={
                "reason": decision.override_reason,
                "urgency": decision.urgency,
            })

        job.status = "completed"
        job.result = {
            "analysis_id": ra.id,
            "reply_id": reply_id,
            "final_status": decision.final_status,
            "auto_reply": decision.auto_reply,
            "is_sensitive": decision.is_sensitive,
        }
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(
            f"Analyzed review {review.id} ({review.platform} {review.rating}★) "
            f"@ {location.name} → status={decision.final_status} "
            f"sensitive={decision.is_sensitive} auto_reply={decision.auto_reply}"
        )

    except Exception as e:
        logger.error(f"task_analyze_review failed for job {job_id}: {e}")
        if job:
            job.status = "failed"
            job.error_message = str(e)[:500]
            try:
                if review:
                    review.status = "failed"
                    _log_action(session, review.id, "analysis_failed",
                                status="failed", error=str(e)[:300])
            except Exception:
                pass
            session.commit()
        raise
    finally:
        session.close()


# ── Post reply to Google ──────────────────────────────────────────────────────

def task_post_reply(job_id: int):
    """Post an approved AI reply to Google Business Profile."""
    session = SyncSessionLocal()
    job = None
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

        # Safety guard: never post to non-Google platforms
        if review.platform != "google":
            job.status = "failed"
            job.error_message = f"Cannot auto-post to platform: {review.platform}"
            session.commit()
            return

        # Safety guard: never post sensitive reviews without manual approval
        if review.is_sensitive:
            job.status = "failed"
            job.error_message = "Blocked: sensitive review — manual review required"
            _log_action(session, review.id, "publish_failed",
                        status="failed", error=job.error_message)
            session.commit()
            return

        if settings.dry_run:
            reply.status = "posted"
            reply.is_dry_run = True
            reply.posted_at = datetime.now(timezone.utc)
            review.status = "auto_replied"
            _log_action(session, review.id, "auto_replied_google",
                        payload={"dry_run": True, "reply_id": reply_id})
            job.status = "completed"
            job.result = {"dry_run": True}
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(f"[DRY RUN] Reply for review {review.id} marked as posted")
            return

        # Live post to Google
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
            review.status = "auto_replied"
            _log_action(session, review.id, "auto_replied_google",
                        payload={"reply_id": reply_id, "location": location.name})
            job.status = "completed"
            job.result = {"posted": True}
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(f"Reply posted for review {review.id} at {location.name}")

        except Exception as post_err:
            job.retry_count += 1
            err_str = str(post_err)[:400]
            if job.retry_count >= job.max_retries:
                job.status = "failed"
                reply.status = "failed"
                reply.error_message = err_str
                review.status = "awaiting_approval"   # fall back to manual approval
                _log_action(session, review.id, "publish_failed",
                            status="failed", error=err_str)
                manager_email = _get_manager_email(session, location.slug)
                if manager_email:
                    send_publish_failure_alert(
                        to_email=manager_email,
                        platform=review.platform,
                        store=location.name,
                        review_id=review.id,
                        error_message=err_str,
                        app_url=settings.app_url,
                    )
            else:
                job.status = "queued"   # re-enqueue for retry
            job.error_message = err_str
            session.commit()
            logger.error(f"Post reply failed (attempt {job.retry_count}): {post_err}")

    except Exception as e:
        logger.error(f"task_post_reply failed for job {job_id}: {e}")
        raise
    finally:
        session.close()


# ── Send alert email ──────────────────────────────────────────────────────────

def task_send_alert_email(job_id: int):
    """Send a manager alert email for a review that needs attention."""
    session = SyncSessionLocal()
    job = None
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
        analysis = session.query(ReviewAnalysis).filter_by(review_id=job.review_id).first()

        if not review or not location:
            job.status = "failed"
            job.error_message = "Missing review or location"
            session.commit()
            return

        manager_email = _get_manager_email(session, location.slug)
        if not manager_email:
            job.status = "failed"
            job.error_message = "No manager email configured"
            session.commit()
            return

        suggested = reply.ai_reply_text if reply else (analysis.suggested_reply if analysis else "")
        issue_types = review.issue_types_json or []
        summary = analysis.summary if analysis else ""

        sent = send_review_alert(
            to_email=manager_email,
            platform=review.platform,
            store=location.name,
            rating=review.rating,
            reviewer=review.reviewer_name or "Anonymous",
            review_text=review.review_text or "",
            urgency=review.urgency or "medium",
            issue_types=issue_types,
            summary=summary,
            suggested_reply=suggested,
            review_url=review.review_url or "",
            review_id=review.id,
            is_sensitive=review.is_sensitive or False,
            app_url=settings.app_url,
        )

        session.add(EmailAlert(
            review_id=review.id,
            recipient=manager_email,
            subject=f"{'🚨 SENSITIVE' if review.is_sensitive else f'[{review.rating}★]'} Review — {location.name}",
            body=f"Review by {review.reviewer_name}: {(review.review_text or '')[:200]}",
            status="sent" if sent else "failed",
            sent_at=datetime.now(timezone.utc) if sent else None,
        ))

        _log_action(session, review.id, "emailed_manager",
                    status="success" if sent else "failed",
                    payload={"to": manager_email, "sent": sent})

        if reply:
            reply.status = "email_sent" if sent else "pending"

        job.status = "completed" if sent else "failed"
        job.result = {"email_sent": sent, "to": manager_email}
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        if not sent:
            logger.warning(f"Alert email failed for review {review.id}")

    except Exception as e:
        logger.error(f"task_send_alert_email failed for job {job_id}: {e}")
        raise
    finally:
        session.close()


# ── Legacy shim ───────────────────────────────────────────────────────────────

def task_generate_reply(job_id: int):
    """Legacy task — redirects to task_analyze_review for backwards compatibility."""
    logger.info(f"Legacy task_generate_reply for job {job_id} → routing to task_analyze_review")
    return task_analyze_review(job_id)
