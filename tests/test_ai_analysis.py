"""
Unit tests for the AI analysis service.
Tests fallback behavior, JSON validation, and output normalization
without making real API calls.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.ai_analysis import (
    _fallback_analysis,
    _validate_analysis,
    _extract_json,
    analyze_review_sync,
)


# ── _fallback_analysis ────────────────────────────────────────────────────────

class TestFallbackAnalysis:
    def test_5star_positive(self):
        result = _fallback_analysis(5, "google")
        assert result["sentiment"] == "positive"
        assert result["urgency"] == "low"
        assert result["auto_reply_allowed"] is True
        assert result["manager_attention_required"] is False
        assert result["suggested_reply"]

    def test_3star_neutral(self):
        result = _fallback_analysis(3, "google")
        assert result["sentiment"] == "neutral"
        assert result["urgency"] == "medium"
        assert result["auto_reply_allowed"] is False
        assert result["manager_attention_required"] is True

    def test_1star_negative(self):
        result = _fallback_analysis(1, "google")
        assert result["sentiment"] == "negative"
        assert result["urgency"] == "high"
        assert result["auto_reply_allowed"] is False
        assert result["manager_attention_required"] is True

    def test_yelp_5star_no_auto_reply(self):
        result = _fallback_analysis(5, "yelp")
        assert result["auto_reply_allowed"] is False


# ── _validate_analysis ────────────────────────────────────────────────────────

class TestValidateAnalysis:
    def test_valid_input(self):
        data = {
            "sentiment": "positive",
            "issue_types": ["service", "food_quality"],
            "urgency": "low",
            "reply_recommended": True,
            "auto_reply_allowed": True,
            "manager_attention_required": False,
            "summary": "Customer was happy.",
            "suggested_reply": "Thank you for the kind words!",
        }
        result = _validate_analysis(data)
        assert result["sentiment"] == "positive"
        assert result["issue_types"] == ["service", "food_quality"]

    def test_invalid_sentiment_defaults_to_neutral(self):
        data = {"sentiment": "very_bad"}
        result = _validate_analysis(data)
        assert result["sentiment"] == "neutral"

    def test_invalid_urgency_defaults_to_low(self):
        data = {"urgency": "extreme"}
        result = _validate_analysis(data)
        assert result["urgency"] == "low"

    def test_unknown_issue_types_filtered(self):
        data = {"issue_types": ["service", "unknown_thing", "food_quality"]}
        result = _validate_analysis(data)
        assert "unknown_thing" not in result["issue_types"]
        assert "service" in result["issue_types"]

    def test_empty_issue_types_defaults_to_other(self):
        data = {"issue_types": []}
        result = _validate_analysis(data)
        assert result["issue_types"] == ["other"]

    def test_summary_truncated_at_1000_chars(self):
        data = {"summary": "x" * 2000}
        result = _validate_analysis(data)
        assert len(result["summary"]) == 1000


# ── _extract_json ─────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_plain_json(self):
        raw = '{"sentiment": "positive", "urgency": "low"}'
        result = _extract_json(raw)
        assert result["sentiment"] == "positive"

    def test_json_with_code_fence(self):
        raw = '```json\n{"sentiment": "negative"}\n```'
        result = _extract_json(raw)
        assert result["sentiment"] == "negative"

    def test_json_with_bare_fence(self):
        raw = '```\n{"urgency": "high"}\n```'
        result = _extract_json(raw)
        assert result["urgency"] == "high"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("not valid json at all")


# ── analyze_review_sync with mocked OpenAI ────────────────────────────────────

class TestAnalyzeReviewSync:
    MOCK_RESPONSE_JSON = json.dumps({
        "sentiment": "positive",
        "issue_types": ["service"],
        "urgency": "low",
        "reply_recommended": True,
        "auto_reply_allowed": True,
        "manager_attention_required": False,
        "summary": "Customer was very happy.",
        "suggested_reply": "Thank you for dining with us!",
    })

    def _make_mock_client(self, content: str):
        mock_choice = MagicMock()
        mock_choice.message.content = content
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        return mock_client

    def test_successful_analysis(self):
        with patch("app.services.ai_analysis.openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = self._make_mock_client(self.MOCK_RESPONSE_JSON)
            result, raw = analyze_review_sync(
                review_text="Amazing food!",
                rating=5,
                reviewer_name="Jane",
                restaurant_name="Raw Sushi",
                location="Stockton, CA",
                platform="google",
                api_key="test-key",
                model="gpt-4o-mini",
            )
        assert result["sentiment"] == "positive"
        assert result["urgency"] == "low"
        assert result["auto_reply_allowed"] is True

    def test_no_api_key_returns_fallback(self):
        result, raw = analyze_review_sync(
            review_text="Great!",
            rating=5,
            reviewer_name="John",
            restaurant_name="Test",
            location="CA",
            platform="google",
            api_key="",
            model="gpt-4o-mini",
        )
        assert result["sentiment"] == "positive"
        raw_data = json.loads(raw)
        assert raw_data.get("fallback") is True

    def test_api_exception_returns_fallback(self):
        with patch("app.services.ai_analysis.openai.OpenAI") as MockOpenAI:
            MockOpenAI.side_effect = Exception("API error")
            result, raw = analyze_review_sync(
                review_text="Terrible!",
                rating=1,
                reviewer_name="Bob",
                restaurant_name="Test",
                location="TX",
                platform="google",
                api_key="test-key",
                model="gpt-4o-mini",
            )
        assert result["sentiment"] == "negative"
        assert result["urgency"] == "high"

    def test_invalid_json_triggers_repair(self):
        """Invalid JSON on first call should attempt repair; fallback on second failure."""
        with patch("app.services.ai_analysis.openai.OpenAI") as MockOpenAI:
            # Both calls return bad JSON
            mock = self._make_mock_client("this is not json")
            mock.chat.completions.create.side_effect = [
                mock.chat.completions.create.return_value,
                mock.chat.completions.create.return_value,
            ]
            MockOpenAI.return_value = mock
            # Should not raise — should return fallback
            result, raw = analyze_review_sync(
                review_text="Some review text.",
                rating=3,
                reviewer_name="Sam",
                restaurant_name="Test",
                location="CA",
                platform="google",
                api_key="test-key",
            )
        # Falls back gracefully
        assert "sentiment" in result
