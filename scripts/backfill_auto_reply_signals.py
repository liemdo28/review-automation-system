"""Normalize legacy reply signals and re-evaluate auto-reply policy for existing reviews."""

from __future__ import annotations

from datetime import datetime

from app.database import SyncSessionLocal
from app.models import Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.ai_reply import sanitize_review_signals
from app.services.auto_reply_policy import (
    count_auto_posts_today_sync,
    evaluate_auto_reply,
    load_effective_auto_reply_config_sync,
)


def main() -> None:
    session = SyncSessionLocal()
    updated = 0
    auto_eligible = 0
    try:
        reviews = session.query(Review).order_by(Review.id).all()
        for review in reviews:
            reply = session.query(Reply).filter(Reply.review_id == review.id).first()
            if not reply:
                continue

            suggestion = (
                session.query(ReplySuggestion)
                .filter(ReplySuggestion.review_id == review.id)
                .order_by(ReplySuggestion.created_at.desc(), ReplySuggestion.id.desc())
                .first()
            )
            source = session.get(ReviewSource, review.source_id) if review.source_id else None
            location = session.get(Location, review.location_id)
            if not location:
                continue

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

            if suggestion:
                suggestion.sentiment = signal_bundle["sentiment"]
                suggestion.issue_tags = signal_bundle["issue_tags"]
                suggestion.risk_flags = signal_bundle["risk_flags"]
                suggestion.reason_summary = signal_bundle["reason_summary"]
                suggestion.confidence_note = signal_bundle["confidence_note"]

            review.issue_category = signal_bundle["issue_category"]
            review.severity_level = signal_bundle["severity_level"]
            review.analysis_summary = signal_bundle["analysis_summary"]
            review.is_flagged = bool(review.rating <= 3)
            if not review.is_flagged:
                review.gm_report_sent = False

            config = load_effective_auto_reply_config_sync(session, location=location)
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
            reply.tone_mode = decision.recommended_tone_mode
            reply.decision_snapshot = {
                **(reply.decision_snapshot or {}),
                **decision.as_dict(),
                "sentiment": signal_bundle["sentiment"],
                "issue_category": signal_bundle["issue_category"],
                "severity_level": signal_bundle["severity_level"],
                "analysis_summary": signal_bundle["analysis_summary"],
            }

            updated += 1
            if decision.allow_auto_post:
                auto_eligible += 1

        session.commit()
        print(f"Backfilled auto-reply signals for {updated} review(s); {auto_eligible} currently auto-eligible.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
