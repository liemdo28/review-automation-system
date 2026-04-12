"""
Unit tests for the business rule engine.
Covers all routing scenarios, sensitive keyword detection,
and platform-specific rules.
"""
import pytest
from app.services.rule_engine import evaluate, check_sensitive, has_negative_signal


# ── check_sensitive ────────────────────────────────────────────────────────────

class TestCheckSensitive:
    def test_food_poisoning(self):
        is_s, matches = check_sensitive("I got food poisoning from this place")
        assert is_s is True
        assert matches

    def test_got_sick(self):
        is_s, _ = check_sensitive("We got sick after eating here")
        assert is_s is True

    def test_allergy(self):
        is_s, _ = check_sensitive("I have a peanut allergy and they didn't warn me")
        assert is_s is True

    def test_raw_chicken(self):
        is_s, _ = check_sensitive("The chicken was raw in the middle")
        assert is_s is True

    def test_insect(self):
        is_s, _ = check_sensitive("Found a cockroach in my soup")
        assert is_s is True

    def test_hair(self):
        is_s, _ = check_sensitive("There was hair in my ramen bowl")
        assert is_s is True

    def test_racism(self):
        is_s, _ = check_sensitive("The staff was racist to us")
        assert is_s is True

    def test_refund(self):
        is_s, _ = check_sensitive("I want a full refund for this terrible meal")
        assert is_s is True

    def test_charged_twice(self):
        is_s, _ = check_sensitive("They charged twice to my card")
        assert is_s is True

    def test_lawsuit(self):
        is_s, _ = check_sensitive("I'm considering legal action")
        assert is_s is True

    def test_health_department(self):
        is_s, _ = check_sensitive("I'm reporting this to the health department")
        assert is_s is True

    def test_not_sensitive_positive(self):
        is_s, _ = check_sensitive("Amazing food, great service, will definitely come back!")
        assert is_s is False

    def test_not_sensitive_mild_complaint(self):
        is_s, _ = check_sensitive("Service was a bit slow but food was good.")
        assert is_s is False

    def test_empty_text(self):
        is_s, _ = check_sensitive("")
        assert is_s is False

    def test_none_text(self):
        is_s, _ = check_sensitive(None)
        assert is_s is False


# ── rule_evaluate — Yelp ──────────────────────────────────────────────────────

class TestYelpRules:
    BASE_ANALYSIS = {
        "sentiment": "positive",
        "issue_types": ["service"],
        "urgency": "low",
        "reply_recommended": True,
        "auto_reply_allowed": True,
        "manager_attention_required": False,
        "summary": "Great experience",
        "suggested_reply": "Thank you!",
    }

    def test_yelp_5star_never_auto_reply(self):
        d = evaluate(
            platform="yelp", rating=5, review_text="Best sushi ever!",
            ai_analysis=self.BASE_ANALYSIS, auto_reply_setting_enabled=True,
        )
        assert d.auto_reply is False
        assert "yelp" in d.override_reason.lower()

    def test_yelp_1star_never_auto_reply(self):
        d = evaluate(
            platform="yelp", rating=1, review_text="Terrible!",
            ai_analysis={**self.BASE_ANALYSIS, "sentiment": "negative", "urgency": "high"},
            auto_reply_setting_enabled=True,
        )
        assert d.auto_reply is False

    def test_yelp_5star_status_is_analyzed(self):
        d = evaluate(
            platform="yelp", rating=5, review_text="Great!",
            ai_analysis=self.BASE_ANALYSIS, auto_reply_setting_enabled=False,
        )
        assert d.final_status == "analyzed"


# ── rule_evaluate — Google ────────────────────────────────────────────────────

class TestGoogleRules:
    POS_ANALYSIS = {
        "sentiment": "positive",
        "issue_types": [],
        "urgency": "low",
        "reply_recommended": True,
        "auto_reply_allowed": True,
        "manager_attention_required": False,
        "summary": "Happy customer",
        "suggested_reply": "Thank you!",
    }

    NEG_ANALYSIS = {
        "sentiment": "negative",
        "issue_types": ["service", "speed"],
        "urgency": "high",
        "reply_recommended": True,
        "auto_reply_allowed": False,
        "manager_attention_required": True,
        "summary": "Complaint about service",
        "suggested_reply": "We apologize...",
    }

    def test_google_5star_auto_reply_when_setting_on(self):
        d = evaluate(
            platform="google", rating=5, review_text="Great food and service!",
            ai_analysis=self.POS_ANALYSIS, auto_reply_setting_enabled=True,
        )
        assert d.auto_reply is True
        assert d.final_status == "approved"

    def test_google_5star_no_auto_reply_when_setting_off(self):
        d = evaluate(
            platform="google", rating=5, review_text="Great food and service!",
            ai_analysis=self.POS_ANALYSIS, auto_reply_setting_enabled=False,
        )
        assert d.auto_reply is False
        assert "auto_reply_google_positive setting is OFF" in d.override_reason

    def test_google_4star_no_negative_signal_auto_reply(self):
        d = evaluate(
            platform="google", rating=4, review_text="Really enjoyed the experience here.",
            ai_analysis=self.POS_ANALYSIS, auto_reply_setting_enabled=True,
        )
        assert d.auto_reply is True

    def test_google_4star_with_negative_signal_no_auto_reply(self):
        d = evaluate(
            platform="google", rating=4,
            review_text="Food was okay but waited too long and would not recommend for service.",
            ai_analysis=self.POS_ANALYSIS, auto_reply_setting_enabled=True,
        )
        assert d.auto_reply is False
        assert "negative signal" in d.override_reason

    def test_google_3star_always_manager_review(self):
        d = evaluate(
            platform="google", rating=3, review_text="It was okay.",
            ai_analysis={**self.POS_ANALYSIS, "urgency": "medium"},
            auto_reply_setting_enabled=True,
        )
        assert d.auto_reply is False
        assert d.final_status == "awaiting_approval"
        assert d.should_send_email is True

    def test_google_2star_high_urgency(self):
        d = evaluate(
            platform="google", rating=2, review_text="Disappointed with everything.",
            ai_analysis=self.NEG_ANALYSIS, auto_reply_setting_enabled=True,
        )
        assert d.urgency == "high"
        assert d.auto_reply is False

    def test_google_1star_escalation(self):
        d = evaluate(
            platform="google", rating=1,
            review_text="Worst experience ever. Will never return.",
            ai_analysis=self.NEG_ANALYSIS, auto_reply_setting_enabled=True,
        )
        assert d.auto_reply is False
        assert d.should_send_email is True


# ── rule_evaluate — Sensitive keyword override ────────────────────────────────

class TestSensitiveOverride:
    POS_ANALYSIS = {
        "sentiment": "positive",
        "issue_types": [],
        "urgency": "low",
        "reply_recommended": True,
        "auto_reply_allowed": True,
        "manager_attention_required": False,
        "summary": "Seemed positive",
        "suggested_reply": "Thank you!",
    }

    def test_sensitive_google_5star_never_auto_reply(self):
        """Even a 5★ Google review with a sensitive keyword must not auto-reply."""
        d = evaluate(
            platform="google", rating=5,
            review_text="Food was great but I think I got food poisoning afterward.",
            ai_analysis=self.POS_ANALYSIS, auto_reply_setting_enabled=True,
        )
        assert d.is_sensitive is True
        assert d.auto_reply is False
        assert d.urgency == "high"
        assert d.final_status == "escalated"

    def test_sensitive_forces_high_urgency(self):
        d = evaluate(
            platform="google", rating=4,
            review_text="Found a hair in my bowl.",
            ai_analysis={**self.POS_ANALYSIS, "urgency": "low"},
            auto_reply_setting_enabled=True,
        )
        assert d.urgency == "high"

    def test_sensitive_always_sends_email(self):
        d = evaluate(
            platform="google", rating=3,
            review_text="Staff was racist and rude to my family.",
            ai_analysis={**self.POS_ANALYSIS, "urgency": "medium"},
            auto_reply_setting_enabled=False,
        )
        assert d.should_send_email is True
        assert d.is_sensitive is True

    def test_refund_demand_sensitive(self):
        d = evaluate(
            platform="yelp", rating=2,
            review_text="I want a full refund. This is unacceptable.",
            ai_analysis={**self.POS_ANALYSIS, "urgency": "medium"},
            auto_reply_setting_enabled=True,
        )
        assert d.is_sensitive is True
        assert d.auto_reply is False
