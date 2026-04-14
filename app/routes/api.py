"""REST API endpoints for review operations."""

from __future__ import annotations

import asyncio
import csv
import subprocess
from datetime import date, datetime
from io import StringIO
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.ai_reply import generate_reply_bundle
from app.services.auto_reply_refresh import apply_auto_reply_decision_async, reevaluate_reviews_for_sources
from app.services.auto_reply_policy import (
    count_auto_posts_today,
    evaluate_auto_reply,
    latest_suggestion_for_review,
    load_effective_auto_reply_config,
    load_global_auto_reply_config,
    save_global_auto_reply_config,
)
from app.services.review_ops import ReviewFilters, apply_review_filters, count_reviews, derive_review_status
from app.services.email_alert import send_daily_negative_review_report as send_daily_negative_review_email
from app.services.gm_report import build_daily_negative_review_report
from app.services.session_resolution import (
    build_shared_key,
    effective_source_url,
    is_shared_session,
    normalize_source_url_override,
    normalize_share_scope,
    resolve_auth_session_for_source,
)
from app.services.source_groups import propagate_group_resolved_url
from app.services.review_views import count_review_listing, fetch_review_listing
from app.workers.fetch_worker import fetch_all_reviews
from app.workers.process_worker import process_queued_jobs

router = APIRouter(tags=["api"])
REPO_ROOT = Path(__file__).resolve().parents[2]


def _enqueue_job_processing(background_tasks: BackgroundTasks | None) -> None:
    if not background_tasks:
        return
    background_tasks.add_task(process_queued_jobs)


def _blocked_reason_label(code: str | None) -> str:
    mapping = {
        "no_session": "Login required",
        "dry_run": "Dry run active",
        "policy_blocked": "Policy blocked",
        "already_replied": "Already handled",
        "missing_reply": "Draft missing",
        "auto_post_disabled": "Auto post disabled",
        "platform_not_live": "Platform not live",
        "not_found": "Review missing",
        "blocked": "Blocked",
    }
    return mapping.get(code or "", "Blocked")


def _blocked_reason_payload(
    *,
    review_id: int,
    code: str,
    label: str,
    detail: str,
    reviewer_name: str | None = None,
    store: str | None = None,
    platform: str | None = None,
    rating: int | None = None,
    decision_reason: str | None = None,
    risk_level: str | None = None,
    workflow_status: str | None = None,
) -> dict:
    payload = {
        "review_id": review_id,
        "reason": label,
        "reason_code": code,
        "reason_detail": detail,
    }
    if reviewer_name:
        payload["reviewer_name"] = reviewer_name
    if store:
        payload["store"] = store
    if platform:
        payload["platform"] = platform
    if rating is not None:
        payload["rating"] = rating
    if decision_reason:
        payload["decision_reason"] = decision_reason
    if risk_level:
        payload["risk_level"] = risk_level
    if workflow_status:
        payload["workflow_status"] = workflow_status
    return payload


class BulkReviewAction(BaseModel):
    review_ids: list[int]
    tone_mode: str | None = None
    handled_by: str | None = "operator"


class BulkAutoReplyStartPayload(BaseModel):
    review_ids: list[int]


class SourceUpdatePayload(BaseModel):
    source_label: str | None = None
    source_url: str | None = None
    resolved_source_url: str | None = None
    auth_mode: str | None = None
    session_status: str | None = None
    settings: dict | None = None
    is_active: bool | None = None


class AuthSessionPayload(BaseModel):
    session_reference: str
    status: str = "active"
    expires_at: datetime | None = None
    share_scope: str | None = None
    shared_key: str | None = None
    source_url_override: str | None = None


class AutoReplyConfigPayload(BaseModel):
    auto_reply_enabled: bool | None = None
    auto_post_phase_enabled: bool | None = None
    auto_reply_google_enabled: bool | None = None
    auto_reply_yelp_enabled: bool | None = None
    auto_reply_min_rating: int | None = None
    auto_reply_daily_limit: int | None = None
    auto_reply_quiet_hours_start: str | None = None
    auto_reply_quiet_hours_end: str | None = None
    auto_reply_confidence_threshold: float | None = None
    auto_reply_blocked_keywords: list[str] | None = None
    auto_reply_escalation_emails: list[str] | None = None
    brand_tone_mode: str | None = None
    max_auto_post_failures: int | None = None


def _direct_source_posting_available(*, platform: str | None) -> bool:
    """Return True only when direct source-portal posting is actually implemented."""
    return (platform or "").strip().lower() == "google"


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    return int(value) if value else None


def _optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    value = value.strip()
    return date.fromisoformat(value) if value else None


def _parse_rating_values(raw_values: list[str] | None, fallback: str | None = None) -> list[int] | None:
    values = list(raw_values or [])
    if fallback is not None:
        values.append(fallback)

    ratings: list[int] = []
    seen: set[int] = set()
    for raw in values:
        if raw is None:
            continue
        for piece in str(raw).split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                rating = int(piece)
            except ValueError:
                continue
            if rating < 1 or rating > 5 or rating in seen:
                continue
            seen.add(rating)
            ratings.append(rating)
    return ratings or None


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


async def _store_session_for_sources(
    db: AsyncSession,
    sources: list[ReviewSource],
    *,
    trace_source: ReviewSource,
    session_reference: str,
    status: str,
    share_scope: str,
    shared_key: str | None,
    source_url_override: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[object, list[int]]:
    from app.models import AuthSession

    updated_source_ids: list[int] = []
    for target_source in sources:
        target_source.session_status = status
        target_source.last_auth_at = datetime.utcnow()
        updated_source_ids.append(target_source.id)

    auth_session = AuthSession(
        source_id=trace_source.id,
        platform=trace_source.platform,
        share_scope=share_scope,
        shared_key=shared_key,
        session_reference=session_reference,
        source_url_override=source_url_override,
        expires_at=expires_at,
        last_validated_at=datetime.utcnow(),
        status=status,
    )
    db.add(auth_session)
    return auth_session, updated_source_ids


async def _ensure_unique_job(
    db: AsyncSession,
    *,
    review_id: int,
    location_id: int,
    source_id: int | None,
    job_type: str,
    payload: dict | None = None,
) -> Job:
    existing = (
        await db.execute(
            select(Job).where(
                Job.review_id == review_id,
                Job.job_type == job_type,
                Job.status.in_(["queued", "processing"]),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    job = Job(
        job_type=job_type,
        review_id=review_id,
        location_id=location_id,
        source_id=source_id,
        status="queued",
        payload=payload,
    )
    db.add(job)
    await db.flush()
    return job


async def _apply_auto_reply_decision(db: AsyncSession, *, review: Review, reply: Reply) -> dict:
    decision = await apply_auto_reply_decision_async(db, review=review, reply=reply)

    if decision.escalation_required:
        await _ensure_unique_job(
            db,
            review_id=review.id,
            location_id=review.location_id,
            source_id=review.source_id,
            job_type="escalate_review",
            payload={"reply_id": reply.id, "decision_reason": decision.decision_reason},
        )

    return decision.as_dict()


async def _queue_ui_posting_job(
    db: AsyncSession,
    *,
    review: Review,
    reply: Reply,
    location: Location | None,
) -> Job:
    config = await load_effective_auto_reply_config(db, location=location)
    if not config.get("auto_post_phase_enabled", False):
        raise HTTPException(409, "Auto-post phase is not enabled in this environment")
    if settings.dry_run:
        raise HTTPException(409, "DRY_RUN is enabled. Turn off dry run before live auto posting.")
    if not review.auto_reply_eligible:
        raise HTTPException(409, "Review is not auto-post eligible")
    if not _direct_source_posting_available(platform=review.platform):
        raise HTTPException(
            409,
            f"Direct posting to {review.platform.title()} is not live yet. START can approve and copy the draft, but staff still need to post it manually on the source page.",
        )

    return await _ensure_unique_job(
        db,
        review_id=review.id,
        location_id=review.location_id,
        source_id=review.source_id,
        job_type="post_ui_reply",
        payload={"reply_id": reply.id, "mode": "ui_fallback"},
    )


def _apply_review_audit(review: Review, bundle: dict) -> None:
    is_flagged = bool(review.rating <= 3)
    review.is_flagged = is_flagged
    review.issue_category = bundle.get("issue_category")
    review.severity_level = bundle.get("severity_level")
    review.analysis_summary = bundle.get("analysis_summary")
    if not is_flagged:
        review.gm_report_sent = False


async def _build_bulk_auto_reply_preview(
    db: AsyncSession,
    *,
    review_ids: list[int],
) -> dict:
    selected_ids: list[int] = []
    seen_ids: set[int] = set()
    for review_id in review_ids:
        if review_id in seen_ids:
            continue
        selected_ids.append(review_id)
        seen_ids.add(review_id)

    eligible_reviews: list[dict] = []
    blocked_reviews: list[dict] = []
    for review_id in selected_ids:
        review = await db.get(Review, review_id)
        if not review:
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=review_id,
                    code="not_found",
                    label="Review missing",
                    detail="Review not found.",
                )
            )
            continue

        location = await db.get(Location, review.location_id)
        source = await db.get(ReviewSource, review.source_id) if review.source_id else None
        reply = (await db.execute(select(Reply).where(Reply.review_id == review.id))).scalar_one_or_none()
        suggestion = await latest_suggestion_for_review(db, review.id)

        if not reply or not (reply.ai_reply_text or "").strip():
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=review.id,
                    code="missing_reply",
                    label="Draft missing",
                    detail="No prepared reply is available yet.",
                    reviewer_name=review.reviewer_name,
                    store=location.name if location else None,
                )
            )
            continue

        if review.has_owner_reply or reply.status == "posted":
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=review.id,
                    code="already_replied",
                    label="Already handled",
                    detail="Owner reply is already visible for this review.",
                    reviewer_name=review.reviewer_name,
                    store=location.name if location else None,
                )
            )
            continue

        if source and source.session_status in {"reauth_required", "failed", "expired", "blocked"}:
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=review.id,
                    code="no_session",
                    label="Login required",
                    detail="Source session needs login before posting can continue.",
                    reviewer_name=review.reviewer_name,
                    store=location.name if location else None,
                )
            )
            continue

        config = await load_effective_auto_reply_config(db, location=location)
        auto_posts_today = await count_auto_posts_today(db, location_id=review.location_id)
        decision = evaluate_auto_reply(
            review,
            source=source,
            config=config,
            suggestion_sentiment=suggestion.sentiment if suggestion else None,
            issue_tags=reply.issue_tags or (suggestion.issue_tags if suggestion else None),
            risk_flags=reply.risk_flags or (suggestion.risk_flags if suggestion else None),
            confidence_note=reply.confidence_note or (suggestion.confidence_note if suggestion else None),
            auto_posts_today=auto_posts_today,
        )

        blocked_reason = None
        blocked_reason_code = None
        if not decision.allow_auto_post:
            blocked_reason = decision.decision_reason
            blocked_reason_code = "policy_blocked"
        elif not config.get("auto_post_phase_enabled", False):
            blocked_reason = "Auto-post phase is disabled in this environment."
            blocked_reason_code = "auto_post_disabled"
        elif settings.dry_run:
            blocked_reason = "DRY_RUN is enabled, so live auto reply is blocked."
            blocked_reason_code = "dry_run"
        elif not _direct_source_posting_available(platform=review.platform):
            blocked_reason = f"{review.platform.title()} auto reply is not live yet."
            blocked_reason_code = "platform_not_live"

        item = {
            "review_id": review.id,
            "reviewer_name": review.reviewer_name,
            "store": location.name if location else None,
            "platform": review.platform,
            "rating": review.rating,
            "decision_reason": decision.decision_reason,
            "risk_level": decision.risk_level,
            "workflow_status": decision.workflow_status,
        }
        if blocked_reason:
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=item["review_id"],
                    code=blocked_reason_code or "blocked",
                    label=_blocked_reason_label(blocked_reason_code),
                    detail=blocked_reason,
                    reviewer_name=item.get("reviewer_name"),
                    store=item.get("store"),
                    platform=item.get("platform"),
                    rating=item.get("rating"),
                    decision_reason=item.get("decision_reason"),
                    risk_level=item.get("risk_level"),
                    workflow_status=item.get("workflow_status"),
                )
            )
        else:
            eligible_reviews.append(item)

    return {
        "selected_count": len(selected_ids),
        "eligible_count": len(eligible_reviews),
        "blocked_count": len(blocked_reviews),
        "eligible_reviews": eligible_reviews,
        "blocked_reviews": blocked_reviews,
    }


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(func.count()).select_from(Location))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "error", "database": str(exc)}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    return {
        "total_unreplied_reviews": await count_reviews(db),
        "google_unreplied_reviews": await count_reviews(db, platform="google"),
        "yelp_unreplied_reviews": await count_reviews(db, platform="yelp"),
        "negative_reviews_needing_attention": await count_reviews(db, negative_only=True),
        "negative_reviews_today": (
            await db.execute(
                select(func.count()).select_from(Review).where(
                    Review.rating <= 3,
                    Review.review_date >= today_start,
                )
            )
        ).scalar()
        or 0,
        "escalated_reviews": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "escalated"))
        ).scalar()
        or 0,
        "reviews_collected_today": (
            await db.execute(select(func.count()).select_from(Review).where(Review.collected_at >= today_start))
        ).scalar()
        or 0,
        "failed_jobs": (
            await db.execute(select(func.count()).select_from(Job).where(Job.status == "failed"))
        ).scalar()
        or 0,
        "auth_expired_jobs": (
            await db.execute(
                select(func.count()).select_from(ReviewSource).where(ReviewSource.session_status == "reauth_required")
            )
        ).scalar()
        or 0,
        "auto_post_eligible_today": (
            await db.execute(
                select(func.count()).select_from(Review).where(
                    Review.auto_reply_eligible.is_(True),
                    Review.last_auto_decision_at >= today_start,
                )
            )
        ).scalar()
        or 0,
        "manual_review_required": (
            await db.execute(
                select(func.count()).select_from(Review).where(Review.workflow_status == "manual_review_required")
            )
        ).scalar()
        or 0,
        "escalated_reviews": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "escalated"))
        ).scalar()
        or 0,
        "blocked_auth_reviews": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "blocked_auth"))
        ).scalar()
        or 0,
    }


@router.get("/reviews")
async def list_reviews(
    request: Request,
    location_id: str | None = None,
    platform: str | None = None,
    rating: str | None = None,
    status: str | None = None,
    date_preset: str | None = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    needs_attention_only: bool = True,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    parsed_location_id = _optional_int(location_id)
    parsed_ratings = _parse_rating_values(request.query_params.getlist("ratings"), rating)
    parsed_rating = parsed_ratings[0] if parsed_ratings and len(parsed_ratings) == 1 else None
    parsed_date_from = _optional_date(date_from)
    parsed_date_to = _optional_date(date_to)
    filters = ReviewFilters(
        location_id=parsed_location_id,
        platform=platform,
        rating=parsed_rating,
        ratings=parsed_ratings,
        status=status,
        date_preset=date_preset,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        needs_attention_only=needs_attention_only,
    )
    order_by = (
        Review.review_date.desc().nullslast(),
        Review.last_seen_at.desc(),
    )
    total = await count_review_listing(db, filters=filters)
    reviews = await fetch_review_listing(db, filters=filters, limit=limit, offset=offset, order_by=order_by)

    items = []
    for item in reviews:
        review = item.review
        reply = item.reply
        source = item.source
        location = item.location
        suggestion = item.suggestion
        items.append(
            {
                "id": review.id,
                "platform": review.platform,
                "store": location.name if location else None,
                "reviewer_name": review.reviewer_name,
                "rating": review.rating,
                "review_text": review.review_text,
                "review_date": review.review_date.isoformat() if review.review_date else None,
                "has_owner_reply": review.has_owner_reply,
                "detected_owner_reply_text": review.detected_owner_reply_text,
                "source_url": review.source_url,
                "suggested_ai_reply": suggestion.suggestion_text if suggestion else reply.ai_reply_text if reply else None,
                "job_source_status": source.session_status if source else None,
                "review_status": item.status,
                "workflow_status": review.workflow_status or item.status,
                "is_handled": review.is_handled,
                "tone_mode": suggestion.tone_mode if suggestion else reply.tone_mode if reply else None,
                "reason_summary": suggestion.reason_summary if suggestion else reply.reason_summary if reply else None,
                "confidence_note": suggestion.confidence_note if suggestion else reply.confidence_note if reply else None,
                "auto_reply_eligible": review.auto_reply_eligible,
                "auto_reply_risk_level": review.auto_reply_risk_level,
                "auto_reply_decision_reason": review.auto_reply_decision_reason,
                "escalated": review.escalated,
                "escalation_reason": review.escalation_reason,
                "is_flagged": review.is_flagged,
                "issue_category": review.issue_category,
                "severity_level": review.severity_level,
                "analysis_summary": review.analysis_summary,
                "gm_report_sent": review.gm_report_sent,
                "posted_by_mode": review.posted_by_mode,
            }
        )

    return {"reviews": items, "count": len(items), "total": total, "offset": offset}


@router.post("/reviews/{review_id}/approve")
async def approve_reply(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (
        await db.execute(select(Reply).where(Reply.review_id == review.id))
    ).scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "No reply found for this review")

    job = Job(
        job_type="post_reply",
        review_id=review.id,
        location_id=review.location_id,
        source_id=review.source_id,
        status="queued",
        payload={"reply_id": reply.id, "mode": "operator_assisted"},
    )
    db.add(job)
    reply.status = "approved"
    review.workflow_status = "approved"
    await db.commit()

    return {"status": "queued", "job_id": job.id, "mode": "operator_assisted"}


@router.post("/reviews/{review_id}/suggestions/regenerate")
async def regenerate_reply(
    review_id: int,
    tone_mode: str = settings.default_reply_tone,
    db: AsyncSession = Depends(get_db),
):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    location = await db.get(Location, review.location_id)
    if not location:
        raise HTTPException(404, "Location not found")

    loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
    bundle = await generate_reply_bundle(
        review_text=review.review_text or "",
        rating=review.rating,
        reviewer_name=review.reviewer_name or "Guest",
        restaurant_name=location.name,
        location=loc_str,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        tone_mode=tone_mode,
    )

    suggestion = ReplySuggestion(
        review_id=review.id,
        tone_mode=tone_mode,
        suggestion_text=bundle["suggestion_text"],
        model_name=settings.openai_model,
        sentiment=bundle.get("sentiment"),
        issue_tags=bundle.get("issue_tags"),
        risk_flags=bundle.get("risk_flags"),
        confidence_note=bundle.get("confidence_note"),
        reason_summary=bundle.get("reason_summary"),
        created_by="operator",
    )
    db.add(suggestion)
    _apply_review_audit(review, bundle)

    reply = (
        await db.execute(select(Reply).where(Reply.review_id == review.id))
    ).scalar_one_or_none()
    if reply:
        reply.ai_reply_text = bundle["suggestion_text"]
        reply.tone_mode = tone_mode
        reply.confidence_note = bundle.get("confidence_note")
        reply.reason_summary = bundle.get("reason_summary")
        reply.issue_tags = bundle.get("issue_tags")
        reply.risk_flags = bundle.get("risk_flags")
        reply.decision_snapshot = {
            **(reply.decision_snapshot or {}),
            "sentiment": bundle.get("sentiment"),
            "issue_category": bundle.get("issue_category"),
            "severity_level": bundle.get("severity_level"),
            "analysis_summary": bundle.get("analysis_summary"),
        }
    else:
        reply = Reply(
            review_id=review.id,
            ai_reply_text=bundle["suggestion_text"],
            ai_model=settings.openai_model,
            tone_mode=tone_mode,
            confidence_note=bundle.get("confidence_note"),
            reason_summary=bundle.get("reason_summary"),
            issue_tags=bundle.get("issue_tags"),
            risk_flags=bundle.get("risk_flags"),
            status="suggested",
            is_dry_run=settings.dry_run,
            decision_snapshot={
                "sentiment": bundle.get("sentiment"),
                "issue_category": bundle.get("issue_category"),
                "severity_level": bundle.get("severity_level"),
                "analysis_summary": bundle.get("analysis_summary"),
            },
        )
        db.add(reply)
        await db.flush()

    decision = await _apply_auto_reply_decision(db, review=review, reply=reply)
    await db.commit()
    return {"status": "ok", "suggestion_id": suggestion.id, "decision": decision}


@router.post("/reviews/bulk/regenerate")
async def bulk_regenerate_reviews(payload: BulkReviewAction, db: AsyncSession = Depends(get_db)):
    tone_mode = payload.tone_mode or settings.default_reply_tone
    created = 0
    for review_id in payload.review_ids:
        review = await db.get(Review, review_id)
        if not review:
            continue
        location = await db.get(Location, review.location_id)
        if not location:
            continue

        loc_str = f"{location.city}, {location.state}" if location.city else location.address or ""
        bundle = await generate_reply_bundle(
            review_text=review.review_text or "",
            rating=review.rating,
            reviewer_name=review.reviewer_name or "Guest",
            restaurant_name=location.name,
            location=loc_str,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            tone_mode=tone_mode,
        )
        db.add(
            ReplySuggestion(
                review_id=review.id,
                tone_mode=tone_mode,
                suggestion_text=bundle["suggestion_text"],
                model_name=settings.openai_model,
                sentiment=bundle.get("sentiment"),
                issue_tags=bundle.get("issue_tags"),
                risk_flags=bundle.get("risk_flags"),
                confidence_note=bundle.get("confidence_note"),
                reason_summary=bundle.get("reason_summary"),
                created_by=payload.handled_by or "operator",
            )
        )
        _apply_review_audit(review, bundle)

        reply = (
            await db.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        if reply:
            reply.ai_reply_text = bundle["suggestion_text"]
            reply.tone_mode = tone_mode
            reply.confidence_note = bundle.get("confidence_note")
            reply.reason_summary = bundle.get("reason_summary")
            reply.issue_tags = bundle.get("issue_tags")
            reply.risk_flags = bundle.get("risk_flags")
            reply.decision_snapshot = {
                **(reply.decision_snapshot or {}),
                "sentiment": bundle.get("sentiment"),
                "issue_category": bundle.get("issue_category"),
                "severity_level": bundle.get("severity_level"),
                "analysis_summary": bundle.get("analysis_summary"),
            }
        else:
            reply = Reply(
                review_id=review.id,
                ai_reply_text=bundle["suggestion_text"],
                ai_model=settings.openai_model,
                tone_mode=tone_mode,
                confidence_note=bundle.get("confidence_note"),
                reason_summary=bundle.get("reason_summary"),
                issue_tags=bundle.get("issue_tags"),
                risk_flags=bundle.get("risk_flags"),
                status="suggested",
                is_dry_run=settings.dry_run,
                decision_snapshot={
                    "sentiment": bundle.get("sentiment"),
                    "issue_category": bundle.get("issue_category"),
                    "severity_level": bundle.get("severity_level"),
                    "analysis_summary": bundle.get("analysis_summary"),
                },
            )
            db.add(reply)
            await db.flush()
        await _apply_auto_reply_decision(db, review=review, reply=reply)
        created += 1

    await db.commit()
    return {"status": "ok", "updated_reviews": created}


@router.post("/reviews/bulk/mark-handled")
async def bulk_mark_handled(payload: BulkReviewAction, db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    count = 0
    for review_id in payload.review_ids:
        review = await db.get(Review, review_id)
        if not review:
            continue
        review.is_handled = True
        review.handled_at = now
        review.handled_by = payload.handled_by or "operator"
        count += 1
    await db.commit()
    return {"status": "ok", "updated_reviews": count}


@router.get("/reviews/selection")
async def select_reviews_for_current_filters(
    request: Request,
    location_id: str | None = None,
    platform: str | None = None,
    rating: str | None = None,
    status: str | None = None,
    date_preset: str | None = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    needs_attention_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    parsed_location_id = _optional_int(location_id)
    parsed_ratings = _parse_rating_values(request.query_params.getlist("ratings"), rating)
    parsed_rating = parsed_ratings[0] if parsed_ratings and len(parsed_ratings) == 1 else None
    parsed_date_from = _optional_date(date_from)
    parsed_date_to = _optional_date(date_to)
    filters = ReviewFilters(
        location_id=parsed_location_id,
        platform=platform,
        rating=parsed_rating,
        ratings=parsed_ratings,
        status=status,
        date_preset=date_preset,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        needs_attention_only=needs_attention_only,
    )
    query = apply_review_filters(select(Review.id), filters).order_by(
        Review.review_date.desc().nullslast(),
        Review.last_seen_at.desc(),
    )
    ids = (await db.execute(query)).scalars().all()
    return {"review_ids": ids, "count": len(ids)}


@router.post("/reviews/bulk/auto-reply-preview")
async def bulk_auto_reply_preview(payload: BulkAutoReplyStartPayload, db: AsyncSession = Depends(get_db)):
    if not payload.review_ids:
        raise HTTPException(400, "No reviews selected")
    return await _build_bulk_auto_reply_preview(db, review_ids=payload.review_ids)


async def _bulk_auto_reply_ui(
    payload: BulkAutoReplyStartPayload,
    db: AsyncSession,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    if not payload.review_ids:
        raise HTTPException(400, "No reviews selected")

    preview = await _build_bulk_auto_reply_preview(db, review_ids=payload.review_ids)
    queued_jobs: list[dict] = []
    blocked_reviews = list(preview["blocked_reviews"])

    for item in preview["eligible_reviews"]:
        review = await db.get(Review, item["review_id"])
        if not review:
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=item["review_id"],
                    code="not_found",
                    label="Review missing",
                    detail="Review not found while queueing.",
                )
            )
            continue
        reply = (await db.execute(select(Reply).where(Reply.review_id == review.id))).scalar_one_or_none()
        if not reply:
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=review.id,
                    code="missing_reply",
                    label="Draft missing",
                    detail="Prepared reply missing while queueing.",
                )
            )
            continue
        location = await db.get(Location, review.location_id)
        try:
            job = await _queue_ui_posting_job(db, review=review, reply=reply, location=location)
        except HTTPException as exc:
            blocked_reviews.append(
                _blocked_reason_payload(
                    review_id=review.id,
                    code="blocked",
                    label=_blocked_reason_label("blocked"),
                    detail=str(exc.detail),
                    reviewer_name=review.reviewer_name,
                    store=location.name if location else None,
                )
            )
            continue
        queued_jobs.append({"review_id": review.id, "job_id": job.id})

    await db.commit()
    _enqueue_job_processing(background_tasks)
    return {
        "status": "queued",
        "selected_count": preview["selected_count"],
        "eligible_count": len(preview["eligible_reviews"]),
        "queued_count": len(queued_jobs),
        "blocked_count": len(blocked_reviews),
        "queued_jobs": queued_jobs,
        "blocked_reviews": blocked_reviews,
        "mode": "ui_fallback",
    }


@router.post("/reviews/bulk/auto-reply-start")
async def bulk_auto_reply_start(payload: BulkAutoReplyStartPayload, db: AsyncSession = Depends(get_db)):
    return await _bulk_auto_reply_ui(payload, db)


@router.post("/reviews/bulk/auto-reply-ui")
async def bulk_auto_reply_ui(
    payload: BulkAutoReplyStartPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    return await _bulk_auto_reply_ui(payload, db, background_tasks)


@router.get("/reviews/export/selected.csv")
async def export_reviews(review_ids: str, db: AsyncSession = Depends(get_db)):
    ids = [int(value) for value in review_ids.split(",") if value.strip().isdigit()]
    if not ids:
        raise HTTPException(400, "No review ids provided")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "review_id",
            "platform",
            "store",
            "reviewer_name",
            "review_date",
            "rating",
            "review_text",
            "has_owner_reply",
            "detected_owner_reply_text",
            "suggested_reply",
            "status",
            "source_url",
        ]
    )

    for review_id in ids:
        review = await db.get(Review, review_id)
        if not review:
            continue
        location = await db.get(Location, review.location_id)
        reply = (
            await db.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        latest_job = (
            await db.execute(select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()).limit(1))
        ).scalar_one_or_none()
        writer.writerow(
            [
                review.id,
                review.platform,
                location.name if location else "",
                review.reviewer_name or "",
                review.review_date.isoformat() if review.review_date else "",
                review.rating,
                review.review_text or "",
                "yes" if review.has_owner_reply else "no",
                review.detected_owner_reply_text or "",
                reply.ai_reply_text if reply else "",
                derive_review_status(review, reply, latest_job),
                review.source_url or "",
            ]
        )

    output.seek(0)
    filename = f"review-export-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reviews/{review_id}")
async def get_review(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")

    reply = (
        await db.execute(select(Reply).where(Reply.review_id == review.id))
    ).scalar_one_or_none()
    location = await db.get(Location, review.location_id)
    source = await db.get(ReviewSource, review.source_id) if review.source_id else None
    jobs = (
        await db.execute(select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()))
    ).scalars().all()
    suggestions = (
        await db.execute(
            select(ReplySuggestion)
            .where(ReplySuggestion.review_id == review.id)
            .order_by(ReplySuggestion.created_at.desc())
        )
    ).scalars().all()

    return {
        "id": review.id,
        "platform": review.platform,
        "external_review_id": review.external_review_id,
        "reviewer_name": review.reviewer_name,
        "rating": review.rating,
        "review_text": review.review_text,
        "review_date": review.review_date.isoformat() if review.review_date else None,
        "has_owner_reply": review.has_owner_reply,
        "detected_owner_reply_text": review.detected_owner_reply_text,
        "detected_owner_reply_at": review.detected_owner_reply_at.isoformat() if review.detected_owner_reply_at else None,
        "is_handled": review.is_handled,
        "workflow_status": review.workflow_status,
        "auto_reply_eligible": review.auto_reply_eligible,
        "auto_reply_decision_reason": review.auto_reply_decision_reason,
        "auto_reply_risk_level": review.auto_reply_risk_level,
        "escalated": review.escalated,
        "escalation_reason": review.escalation_reason,
        "is_flagged": review.is_flagged,
        "issue_category": review.issue_category,
        "severity_level": review.severity_level,
        "analysis_summary": review.analysis_summary,
        "gm_report_sent": review.gm_report_sent,
        "posted_by_mode": review.posted_by_mode,
        "policy_version": review.policy_version,
        "last_auto_decision_at": review.last_auto_decision_at.isoformat() if review.last_auto_decision_at else None,
        "handled_at": review.handled_at.isoformat() if review.handled_at else None,
        "handled_by": review.handled_by,
        "source": {
            "id": source.id,
            "label": source.source_label,
            "url": source.source_url,
            "resolved_url": source.resolved_source_url,
            "auth_mode": source.auth_mode,
            "session_status": source.session_status,
        }
        if source
        else None,
        "location": {"id": location.id, "name": location.name, "slug": location.slug} if location else None,
        "reply": {
            "id": reply.id,
            "text": reply.ai_reply_text,
            "status": reply.status,
            "model": reply.ai_model,
            "tone_mode": reply.tone_mode,
            "confidence_note": reply.confidence_note,
            "reason_summary": reply.reason_summary,
            "issue_tags": reply.issue_tags,
            "risk_flags": reply.risk_flags,
            "decision_snapshot": reply.decision_snapshot,
            "is_dry_run": reply.is_dry_run,
            "posted_at": reply.posted_at.isoformat() if reply.posted_at else None,
            "posted_by_mode": reply.posted_by_mode,
            "last_auto_post_error": reply.last_auto_post_error,
            "last_auto_post_at": reply.last_auto_post_at.isoformat() if reply.last_auto_post_at else None,
        }
        if reply
        else None,
        "suggestions": [
            {
                "id": item.id,
                "tone_mode": item.tone_mode,
                "suggestion_text": item.suggestion_text,
                "sentiment": item.sentiment,
                "issue_tags": item.issue_tags,
                "risk_flags": item.risk_flags,
                "confidence_note": item.confidence_note,
                "reason_summary": item.reason_summary,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in suggestions
        ],
        "jobs": [
            {
                "id": job.id,
                "job_type": job.job_type,
                "status": job.status,
                "retry_count": job.retry_count,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "error_message": job.error_message,
            }
            for job in jobs
        ],
        "raw_payload": review.raw_payload or review.raw_data,
    }


@router.get("/locations")
async def list_locations(db: AsyncSession = Depends(get_db)):
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    return [
        {
            "id": location.id,
            "slug": location.slug,
            "name": location.name,
            "address": location.address,
            "city": location.city,
            "state": location.state,
            "is_active": location.is_active,
            "auto_reply_settings": location.auto_reply_settings or {},
        }
        for location in locations
    ]


@router.post("/reviews/{review_id}/evaluate-auto-reply")
async def evaluate_auto_reply_for_review(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    reply = (await db.execute(select(Reply).where(Reply.review_id == review.id))).scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "No reply found for this review")

    decision = await _apply_auto_reply_decision(db, review=review, reply=reply)
    await db.commit()
    return {"status": "ok", "decision": decision}


@router.post("/reviews/bulk/evaluate-auto-reply")
async def bulk_evaluate_auto_reply(payload: BulkReviewAction, db: AsyncSession = Depends(get_db)):
    updated = 0
    decisions: list[dict] = []
    for review_id in payload.review_ids:
        review = await db.get(Review, review_id)
        if not review:
            continue
        reply = (await db.execute(select(Reply).where(Reply.review_id == review.id))).scalar_one_or_none()
        if not reply:
            continue
        decision = await _apply_auto_reply_decision(db, review=review, reply=reply)
        decisions.append({"review_id": review.id, "decision": decision})
        updated += 1
    await db.commit()
    return {"status": "ok", "updated_reviews": updated, "decisions": decisions}


@router.post("/reviews/{review_id}/mark-escalated")
async def mark_review_escalated(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    review.workflow_status = "escalated"
    review.escalated = True
    review.escalation_reason = review.escalation_reason or "Escalated by operator."
    review.last_auto_decision_at = datetime.utcnow()
    await db.commit()
    return {"status": "ok", "workflow_status": review.workflow_status}


@router.post("/reviews/{review_id}/mark-manual")
async def mark_review_manual(review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    review.workflow_status = "manual_review_required"
    review.auto_reply_eligible = False
    review.escalated = False
    review.last_auto_decision_at = datetime.utcnow()
    await db.commit()
    return {"status": "ok", "workflow_status": review.workflow_status}


async def _queue_single_auto_reply_ui(
    review_id: int,
    db: AsyncSession,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    reply = (await db.execute(select(Reply).where(Reply.review_id == review.id))).scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "No reply found for this review")

    location = await db.get(Location, review.location_id)
    job = await _queue_ui_posting_job(db, review=review, reply=reply, location=location)
    await db.commit()
    _enqueue_job_processing(background_tasks)
    return {"status": "queued", "job_id": job.id, "mode": "ui_fallback"}


@router.post("/reviews/{review_id}/retry-auto-post")
async def retry_auto_post(
    review_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    return await _queue_single_auto_reply_ui(review_id, db, background_tasks)


@router.post("/reviews/{review_id}/auto-reply-ui")
async def auto_reply_ui(
    review_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    return await _queue_single_auto_reply_ui(review_id, db, background_tasks)


@router.get("/admin/auto-reply-config")
async def get_auto_reply_config(db: AsyncSession = Depends(get_db)):
    return await load_global_auto_reply_config(db)


@router.patch("/admin/auto-reply-config")
async def patch_auto_reply_config(payload: AutoReplyConfigPayload, db: AsyncSession = Depends(get_db)):
    current = await load_global_auto_reply_config(db)
    current.update(payload.model_dump(exclude_unset=True))
    config = await save_global_auto_reply_config(db, current)
    await db.commit()
    return {"status": "ok", "config": config}


@router.patch("/locations/{location_id}/auto-reply-config")
async def patch_location_auto_reply_config(
    location_id: int,
    payload: AutoReplyConfigPayload,
    db: AsyncSession = Depends(get_db),
):
    location = await db.get(Location, location_id)
    if not location:
        raise HTTPException(404, "Location not found")
    merged = dict(location.auto_reply_settings or {})
    merged.update(payload.model_dump(exclude_unset=True))
    location.auto_reply_settings = merged
    await db.commit()
    return {"status": "ok", "location_id": location.id, "config": location.auto_reply_settings}


@router.get("/auto-reply/stats")
async def auto_reply_stats(db: AsyncSession = Depends(get_db)):
    return {
        "auto_post_eligible": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "auto_post_eligible"))
        ).scalar()
        or 0,
        "manual_review_required": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "manual_review_required"))
        ).scalar()
        or 0,
        "escalated": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "escalated"))
        ).scalar()
        or 0,
        "blocked_auth": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "blocked_auth"))
        ).scalar()
        or 0,
        "posted_automatically": (
            await db.execute(select(func.count()).select_from(Reply).where(Reply.posted_by_mode == "auto"))
        ).scalar()
        or 0,
        "flagged_reviews": (
            await db.execute(select(func.count()).select_from(Review).where(Review.is_flagged.is_(True)))
        ).scalar()
        or 0,
        "negative_reviews_today": (
            await db.execute(
                select(func.count()).select_from(Review).where(
                    Review.rating <= 3,
                    Review.review_date >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
                )
            )
        ).scalar()
        or 0,
    }


@router.get("/auto-reply/failures")
async def auto_reply_failures(limit: int = 25, db: AsyncSession = Depends(get_db)):
    replies = (
        await db.execute(
            select(Reply)
            .where(Reply.last_auto_post_error.is_not(None))
            .order_by(Reply.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "review_id": reply.review_id,
            "reply_id": reply.id,
            "auto_post_attempts": reply.auto_post_attempts,
            "last_auto_post_error": reply.last_auto_post_error,
            "last_auto_post_at": reply.last_auto_post_at.isoformat() if reply.last_auto_post_at else None,
        }
        for reply in replies
    ]


@router.get("/auto-reply/escalations")
async def auto_reply_escalations(limit: int = 25, db: AsyncSession = Depends(get_db)):
    reviews = (
        await db.execute(
            select(Review)
            .where(Review.workflow_status == "escalated")
            .order_by(Review.last_auto_decision_at.desc().nullslast(), Review.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "review_id": review.id,
            "location_id": review.location_id,
            "platform": review.platform,
            "reviewer_name": review.reviewer_name,
            "rating": review.rating,
            "decision_reason": review.auto_reply_decision_reason,
            "escalation_reason": review.escalation_reason,
            "last_auto_decision_at": review.last_auto_decision_at.isoformat() if review.last_auto_decision_at else None,
        }
        for review in reviews
    ]


@router.get("/auto-reply/reports/daily-negative")
async def daily_negative_report(db: AsyncSession = Depends(get_db)):
    report = await build_daily_negative_review_report(db)
    return {
        "title": report.title,
        "report_date": report.report_date,
        "total_reviews": report.total_reviews,
        "by_store": report.by_store,
        "by_issue_type": report.by_issue_type,
        "serious_issues": report.serious_issues,
        "suggested_actions": report.suggested_actions,
        "body": report.body,
    }


@router.post("/auto-reply/reports/daily-negative/send")
async def send_daily_negative_report(db: AsyncSession = Depends(get_db)):
    report = await build_daily_negative_review_report(db)
    recipients: list[str] = []
    if settings.alert_email_to:
        recipients.extend([item.strip() for item in settings.alert_email_to.split(",") if item.strip()])
    sent = send_daily_negative_review_email(report.title, report.body, recipients)
    if sent:
        reviews = (
            await db.execute(select(Review).where(Review.id.in_(report.review_ids)))
        ).scalars().all() if report.review_ids else []
        for review in reviews:
            review.gm_report_sent = True
        await db.commit()
    return {"status": "sent" if sent else "failed", "recipient_count": len(recipients), "review_count": report.total_reviews}


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)):
    sources = (await db.execute(select(ReviewSource).order_by(ReviewSource.location_id, ReviewSource.platform))).scalars().all()
    items = []
    for source in sources:
        location = await db.get(Location, source.location_id)
        auth_session = await resolve_auth_session_for_source(db, source, location=location)
        items.append(
            {
                "id": source.id,
                "location_id": source.location_id,
                "platform": source.platform,
                "source_url": source.source_url,
                "resolved_source_url": source.resolved_source_url,
                "effective_source_url": effective_source_url(source, auth_session),
                "source_label": source.source_label,
                "auth_mode": source.auth_mode,
                "session_status": source.session_status,
                "last_auth_at": source.last_auth_at.isoformat() if source.last_auth_at else None,
                "last_successful_sync_at": source.last_successful_sync_at.isoformat() if source.last_successful_sync_at else None,
                "last_failed_sync_at": source.last_failed_sync_at.isoformat() if source.last_failed_sync_at else None,
                "is_active": source.is_active,
                "using_shared_session": is_shared_session(auth_session, source),
                "effective_session": {
                    "id": auth_session.id,
                    "share_scope": auth_session.share_scope,
                    "shared_key": auth_session.shared_key,
                    "session_reference": auth_session.session_reference,
                    "last_validated_at": auth_session.last_validated_at.isoformat() if auth_session.last_validated_at else None,
                    "expires_at": auth_session.expires_at.isoformat() if auth_session.expires_at else None,
                    "status": auth_session.status,
                }
                if auth_session
                else None,
            }
        )
    return items


@router.patch("/sources/{source_id}")
async def update_source(source_id: int, payload: SourceUpdatePayload, db: AsyncSession = Depends(get_db)):
    source = await db.get(ReviewSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    previous_session_status = source.session_status
    previous_effective_url = source.resolved_source_url or source.source_url
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(source, field, value)
    should_refresh_decisions = (
        source.session_status == "active"
        and (
            previous_session_status != "active"
            or (source.resolved_source_url or source.source_url) != previous_effective_url
        )
    )
    refresh_result = {"updated_reviews": 0}
    if should_refresh_decisions:
        refresh_result = await reevaluate_reviews_for_sources(db, source_ids=[source.id])
    await db.commit()
    return {"status": "ok", "source_id": source.id, "reevaluated_reviews": refresh_result["updated_reviews"]}


@router.post("/sources/{source_id}/sessions")
async def create_source_session(
    source_id: int,
    payload: AuthSessionPayload,
    share_scope: str = "source",
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(ReviewSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    resolved_share_scope = normalize_share_scope(payload.share_scope or share_scope)
    if resolved_share_scope not in {"source", "platform", "account"}:
        raise HTTPException(400, "share_scope must be 'source', 'platform', or 'account'")

    target_sources = [source]
    location = await db.get(Location, source.location_id)
    if resolved_share_scope == "platform":
        target_sources = (
            await db.execute(
                select(ReviewSource)
                .where(
                    ReviewSource.platform == source.platform,
                    ReviewSource.is_active.is_(True),
                )
                .order_by(ReviewSource.location_id, ReviewSource.id)
            )
        ).scalars().all()
    elif resolved_share_scope == "account":
        account_id = location.google_account_id if location and source.platform == "google" else None
        if account_id:
            target_sources = (
                await db.execute(
                    select(ReviewSource)
                    .join(Location, Location.id == ReviewSource.location_id)
                    .where(
                        ReviewSource.platform == source.platform,
                        ReviewSource.is_active.is_(True),
                        Location.google_account_id == account_id,
                    )
                    .order_by(ReviewSource.location_id, ReviewSource.id)
                )
            ).scalars().all()

    resolved_shared_key = build_shared_key(
        platform=source.platform,
        share_scope=resolved_share_scope,
        source_id=source.id,
        location=location,
        shared_key=payload.shared_key,
    )

    normalized_source_override = normalize_source_url_override(source.platform, payload.source_url_override)

    auth_session, updated_source_ids = await _store_session_for_sources(
        db,
        target_sources,
        trace_source=source,
        session_reference=payload.session_reference,
        status=payload.status,
        share_scope=resolved_share_scope,
        shared_key=resolved_shared_key,
        source_url_override=normalized_source_override,
        expires_at=payload.expires_at,
    )

    resolved_source_url_updated = False
    resolved_source_updated_ids: list[int] = []
    if normalized_source_override:
        resolved_source_updated_ids = await propagate_group_resolved_url(db, source, normalized_source_override)
        resolved_source_url_updated = True

    refresh_result = {"updated_reviews": 0}
    if payload.status == "active":
        refresh_ids = list({*updated_source_ids, *resolved_source_updated_ids})
        refresh_result = await reevaluate_reviews_for_sources(db, source_ids=refresh_ids)

    await db.commit()
    return {
        "status": "ok",
        "session_id": auth_session.id,
        "share_scope": resolved_share_scope,
        "shared_key": resolved_shared_key,
        "updated_source_ids": updated_source_ids,
        "source_url_updated": resolved_source_url_updated,
        "source_url": normalized_source_override if resolved_source_url_updated else None,
        "resolved_source_updated_ids": resolved_source_updated_ids,
        "reevaluated_reviews": refresh_result["updated_reviews"],
    }


@router.post("/sources/{source_id}/bootstrap")
async def bootstrap_source_session(
    source_id: int,
    share_scope: str = "source",
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(ReviewSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if not source.source_url:
        raise HTTPException(400, "Source URL is missing")
    resolved_share_scope = normalize_share_scope(share_scope)
    if resolved_share_scope not in {"source", "platform", "account"}:
        raise HTTPException(400, "share_scope must be 'source', 'platform', or 'account'")

    session_dir = _repo_path(settings.session_storage_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    if resolved_share_scope == "platform":
        session_path = session_dir / f"{source.platform}-shared-session.json"
        launch_label = f"All {source.platform.title()} Sources"
        if source.platform == "google":
            launch_url = settings.google_login_url
        elif source.platform == "yelp":
            launch_url = settings.yelp_login_url
        else:
            launch_url = source.source_url
    else:
        session_path = session_dir / f"source-{source.id}-{source.platform}.json"
        launch_label = source.source_label or f"{source.platform.title()} source"
        launch_url = source.source_url
    script_path = REPO_ROOT / "scripts" / "bootstrap_source_session.ps1"
    if not script_path.exists():
        raise HTTPException(500, "Bootstrap script is missing")

    command = [
        "powershell.exe",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-SourceId",
        str(source.id),
        "-ShareScope",
        resolved_share_scope,
        "-Platform",
        source.platform,
        "-SourceUrl",
        launch_url,
        "-SourceLabel",
        launch_label,
        "-OutputPath",
        str(session_path),
        "-ApiBaseUrl",
        "http://127.0.0.1:8000",
    ]

    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        subprocess.Popen(command, cwd=str(REPO_ROOT), creationflags=creationflags)
    except OSError as exc:
        raise HTTPException(500, f"Unable to launch bootstrap window: {exc}") from exc

    source.session_status = "reauth_required"
    await db.commit()
    return {
        "status": "bootstrap_started",
        "source_id": source.id,
        "share_scope": resolved_share_scope,
        "session_path": str(session_path),
        "platform": source.platform,
        "source_label": launch_label,
        "launch_url": launch_url,
    }


@router.post("/fetch/trigger")
async def trigger_fetch(
    location_id: int | None = None,
    platform: str | None = None,
    source_id: int | None = None,
):
    asyncio.create_task(
        fetch_all_reviews(location_id=location_id, platform=platform, source_id=source_id)
    )
    return {"status": "fetch_triggered"}


@router.get("/jobs")
async def list_jobs(limit: int = 20, db: AsyncSession = Depends(get_db)):
    jobs = (
        await db.execute(select(Job).order_by(desc(Job.queued_at)).limit(limit))
    ).scalars().all()
    return [
        {
            "id": job.id,
            "type": job.job_type,
            "status": job.status,
            "review_id": job.review_id,
            "source_id": job.source_id,
            "retry_count": job.retry_count,
            "queued_at": job.queued_at.isoformat() if job.queued_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error": job.error_message,
        }
        for job in jobs
    ]
