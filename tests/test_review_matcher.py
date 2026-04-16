from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services.review_matcher import CandidateReviewCard, find_best_review_match, normalize_match_text


def test_normalize_match_text_compacts_whitespace():
    assert normalize_match_text("  Great   Service \n Today ") == "great service today"


def test_review_matcher_picks_exact_candidate():
    review = SimpleNamespace(
        external_review_id="abc-123",
        reviewer_name="John Smith",
        review_text="Amazing ramen and fantastic service.",
        rating=5,
        review_date=datetime(2026, 4, 16),
    )
    candidates = [
        CandidateReviewCard(
            reviewer_name="Jane Doe",
            review_text="Pretty good.",
            rating=4,
            review_date_raw="2026-04-10",
            external_review_id="other",
        ),
        CandidateReviewCard(
            reviewer_name="John Smith",
            review_text="Amazing ramen and fantastic service.",
            rating=5,
            review_date_raw="2026-04-16",
            external_review_id="abc-123",
        ),
    ]

    result = find_best_review_match(review, candidates, threshold=0.78, min_margin=0.08)

    assert result.matched
    assert result.candidate is not None
    assert result.candidate.reviewer_name == "John Smith"


def test_review_matcher_rejects_ambiguous_match():
    review = SimpleNamespace(
        external_review_id=None,
        reviewer_name="Alex",
        review_text="Good food and nice service.",
        rating=5,
        review_date=datetime(2026, 4, 16),
    )
    candidates = [
        CandidateReviewCard("Alex", "Good food and nice service.", 5, "2026-04-16"),
        CandidateReviewCard("Alex", "Good food nice service.", 5, "2026-04-16"),
    ]

    result = find_best_review_match(review, candidates, threshold=0.78, min_margin=0.2)

    assert not result.matched
    assert "ambiguous_match" in result.reasons
