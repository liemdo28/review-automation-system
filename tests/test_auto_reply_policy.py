from __future__ import annotations

from types import SimpleNamespace

from app.services.auto_reply_policy import default_auto_reply_config, evaluate_auto_reply


def _review(**overrides):
    payload = {
        "rating": 5,
        "review_text": "Amazing ramen and great service.",
        "has_owner_reply": False,
        "platform": "google",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _source(session_status: str = "active", is_active: bool = True):
    return SimpleNamespace(session_status=session_status, is_active=is_active)


def test_low_rating_is_escalated():
    decision = evaluate_auto_reply(
        _review(rating=1, review_text="Terrible service"),
        source=_source(),
        config=default_auto_reply_config(),
        suggestion_sentiment="negative",
        issue_tags=["service"],
        risk_flags=[],
        confidence_note="High confidence",
    )

    assert not decision.allow_auto_post
    assert decision.escalation_required
    assert decision.workflow_status == "escalated"


def test_five_star_google_review_can_queue_auto_post_when_live():
    config = default_auto_reply_config()
    config["auto_post_phase_enabled"] = True

    decision = evaluate_auto_reply(
        _review(),
        source=_source(),
        config=config,
        suggestion_sentiment="positive",
        issue_tags=["positive_compliment"],
        risk_flags=[],
        confidence_note="High confidence from clear text and rating signals.",
        auto_posts_today=0,
    )

    assert decision.allow_auto_post
    assert decision.queue_auto_post
    assert decision.workflow_status == "auto_post_eligible"


def test_inactive_source_blocks_live_auto_post():
    config = default_auto_reply_config()
    config["auto_post_phase_enabled"] = True

    decision = evaluate_auto_reply(
        _review(),
        source=_source(session_status="reauth_required"),
        config=config,
        suggestion_sentiment="positive",
        issue_tags=["positive_compliment"],
        risk_flags=[],
        confidence_note="High confidence from clear text and rating signals.",
    )

    assert decision.allow_auto_post
    assert not decision.queue_auto_post
    assert decision.workflow_status == "blocked_auth"
