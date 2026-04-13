from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location, Reply, Review, ReviewSource
from app.services.ai_reply import sanitize_review_signals
from app.services.auto_reply_policy import (
    count_auto_posts_today,
    evaluate_auto_reply,
    latest_suggestion_for_review,
    load_effective_auto_reply_config,
)


async def apply_auto_reply_decision_async(
    db: AsyncSession,
    *,
    review: Review,
    reply: Reply,
    source: ReviewSource | None = None,
    location: Location | None = None,
) -> dict:
    resolved_location = location or await db.get(Location, review.location_id)
    resolved_source = source or (await db.get(ReviewSource, review.source_id) if review.source_id else None)
    config = await load_effective_auto_reply_config(db, location=resolved_location)
    suggestion = await latest_suggestion_for_review(db, review.id)
    signal_bundle = sanitize_review_signals(
        review.review_text or "",
        review.rating,
        issue_tags=reply.issue_tags or (suggestion.issue_tags if suggestion else None),
        risk_flags=reply.risk_flags or (suggestion.risk_flags if suggestion else None),
        sentiment=suggestion.sentiment if suggestion else None,
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
    auto_posts_today = await count_auto_posts_today(db, location_id=review.location_id)
    decision = evaluate_auto_reply(
        review,
        source=resolved_source,
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

    reply.tone_mode = decision.recommended_tone_mode
    reply.decision_snapshot = {**(reply.decision_snapshot or {}), **decision.as_dict()}
    reply.decision_snapshot["sentiment"] = signal_bundle["sentiment"]
    reply.decision_snapshot["issue_category"] = signal_bundle["issue_category"]
    reply.decision_snapshot["severity_level"] = signal_bundle["severity_level"]
    reply.decision_snapshot["analysis_summary"] = signal_bundle["analysis_summary"]

    if suggestion:
        suggestion.sentiment = signal_bundle["sentiment"]
        suggestion.issue_tags = signal_bundle["issue_tags"]
        suggestion.risk_flags = signal_bundle["risk_flags"]
        suggestion.reason_summary = signal_bundle["reason_summary"]
        suggestion.confidence_note = signal_bundle["confidence_note"]

    return decision.as_dict()


async def reevaluate_reviews_for_sources(
    db: AsyncSession,
    *,
    source_ids: list[int],
    require_active: bool = True,
) -> dict:
    unique_source_ids = sorted({source_id for source_id in source_ids if source_id})
    if not unique_source_ids:
        return {"source_ids": [], "review_ids": [], "updated_reviews": 0}

    sources = (
        await db.execute(select(ReviewSource).where(ReviewSource.id.in_(unique_source_ids)))
    ).scalars().all()
    if require_active:
        sources = [source for source in sources if (source.session_status or "").lower() == "active"]
    if not sources:
        return {"source_ids": [], "review_ids": [], "updated_reviews": 0}

    source_ids_to_refresh = [source.id for source in sources]
    locations = (
        await db.execute(select(Location).where(Location.id.in_([source.location_id for source in sources])))
    ).scalars().all()
    locations_by_id = {location.id: location for location in locations}
    sources_by_id = {source.id: source for source in sources}

    rows = (
        await db.execute(
            select(Review, Reply)
            .join(Reply, Reply.review_id == Review.id)
            .where(
                Review.source_id.in_(source_ids_to_refresh),
                Review.has_owner_reply.is_not(True),
                Reply.status != "posted",
            )
            .order_by(Review.id)
        )
    ).all()

    updated_review_ids: list[int] = []
    for review, reply in rows:
        await apply_auto_reply_decision_async(
            db,
            review=review,
            reply=reply,
            source=sources_by_id.get(review.source_id),
            location=locations_by_id.get(review.location_id),
        )
        updated_review_ids.append(review.id)

    return {
        "source_ids": source_ids_to_refresh,
        "review_ids": updated_review_ids,
        "updated_reviews": len(updated_review_ids),
    }
