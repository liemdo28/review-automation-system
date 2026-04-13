from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

from app.providers.base import ReviewProvider


@dataclass(slots=True)
class CandidateReviewCard:
    reviewer_name: str
    review_text: str
    rating: int
    review_date_raw: str | None = None
    external_review_id: str | None = None
    raw_text: str | None = None
    has_owner_reply: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReviewMatchResult:
    matched: bool
    score: float
    confidence: str
    reasons: list[str]
    candidate: CandidateReviewCard | None = None
    second_best_score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.candidate:
            payload["candidate"] = self.candidate.as_dict()
        return payload


def normalize_match_text(value: str | None) -> str:
    text = ReviewProvider.normalize_text(value) or ""
    return " ".join(text.lower().split())


def review_text_snippet(value: str | None, *, limit: int = 140) -> str:
    text = normalize_match_text(value)
    return text[:limit]


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _date_score(review_date, candidate_date_raw: str | None) -> tuple[float, str | None]:
    if not review_date or not candidate_date_raw:
        return 0.0, None
    candidate_date = ReviewProvider.parse_datetime(candidate_date_raw)
    if not candidate_date:
        return 0.0, None

    delta_days = abs((review_date.date() - candidate_date.date()).days)
    if delta_days == 0:
        return 0.12, "date_exact"
    if delta_days <= 2:
        return 0.08, "date_close"
    if delta_days <= 7:
        return 0.04, "date_near"
    return 0.0, None


def score_review_match(review, candidate: CandidateReviewCard) -> ReviewMatchResult:
    reasons: list[str] = []
    score = 0.0

    target_external_id = (getattr(review, "external_review_id", None) or "").strip().lower()
    candidate_external_id = (candidate.external_review_id or "").strip().lower()
    if target_external_id and candidate_external_id and target_external_id == candidate_external_id:
        score += 1.0
        reasons.append("external_id_exact")

    target_name = normalize_match_text(getattr(review, "reviewer_name", None))
    candidate_name = normalize_match_text(candidate.reviewer_name)
    if target_name and candidate_name:
        if target_name == candidate_name:
            score += 0.38
            reasons.append("reviewer_exact")
        elif target_name in candidate_name or candidate_name in target_name:
            score += 0.22
            reasons.append("reviewer_partial")

    target_snippet = review_text_snippet(getattr(review, "review_text", None))
    candidate_snippet = review_text_snippet(candidate.review_text or candidate.raw_text)
    similarity = _text_similarity(target_snippet, candidate_snippet)
    if similarity >= 0.92:
        score += 0.38
        reasons.append("text_exactish")
    elif similarity >= 0.8:
        score += 0.28
        reasons.append("text_strong")
    elif similarity >= 0.68:
        score += 0.18
        reasons.append("text_partial")

    review_rating = int(getattr(review, "rating", 0) or 0)
    if review_rating and candidate.rating and review_rating == candidate.rating:
        score += 0.14
        reasons.append("rating_match")

    date_score, date_reason = _date_score(getattr(review, "review_date", None), candidate.review_date_raw)
    score += date_score
    if date_reason:
        reasons.append(date_reason)

    confidence = "low"
    if score >= 0.9:
        confidence = "high"
    elif score >= 0.78:
        confidence = "medium"

    return ReviewMatchResult(
        matched=False,
        score=round(score, 4),
        confidence=confidence,
        reasons=reasons,
        candidate=candidate,
    )


def find_best_review_match(
    review,
    candidates: list[CandidateReviewCard],
    *,
    threshold: float,
    min_margin: float,
) -> ReviewMatchResult:
    scored = [score_review_match(review, candidate) for candidate in candidates]
    if not scored:
        return ReviewMatchResult(
            matched=False,
            score=0.0,
            confidence="low",
            reasons=["no_candidates"],
        )

    ranked = sorted(scored, key=lambda item: item.score, reverse=True)
    best = ranked[0]
    second_best = ranked[1].score if len(ranked) > 1 else 0.0
    matched = best.score >= threshold and (best.score - second_best) >= min_margin
    reasons = list(best.reasons)
    if not matched:
        if best.score < threshold:
            reasons.append("below_threshold")
        if (best.score - second_best) < min_margin:
            reasons.append("ambiguous_match")

    return ReviewMatchResult(
        matched=matched,
        score=best.score,
        confidence=best.confidence,
        reasons=reasons,
        candidate=best.candidate,
        second_best_score=round(second_best, 4),
    )
