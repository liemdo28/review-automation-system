"""AI reply generation and lightweight review classification."""

from __future__ import annotations

import json
import logging
from typing import Any

import openai

logger = logging.getLogger("review_system.ai_reply")

STAR_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
SUPPORTED_TONES = {
    "gentle_professional": "Gentle professional",
    "warm_hospitality": "Warm hospitality",
    "premium_brand": "Premium brand tone",
}

SYSTEM_PROMPT = (
    "You are a restaurant reputation management assistant.\n"
    "Produce culturally appropriate, natural, professional reply suggestions for restaurant reviews.\n"
    "Rules:\n"
    "- Never mention AI.\n"
    "- Do not invent facts.\n"
    "- Do not argue with the customer.\n"
    "- Do not over-apologize.\n"
    "- Do not offer compensation, refunds, or discounts unless explicitly told.\n"
    "- Negative reviews should acknowledge the concern, protect the brand, and invite offline follow-up if needed.\n"
    "- Positive reviews should thank the guest warmly, reinforce trust, and invite them back naturally.\n"
    "- Output valid JSON with keys: suggestion_text, sentiment, issue_tags, risk_flags, confidence_note, reason_summary."
)


def normalize_rating(raw: Any) -> int:
    if isinstance(raw, int):
        return max(1, min(5, raw))
    return STAR_MAP.get(str(raw).upper(), 0)


def classify_review(review_text: str, rating: int) -> dict[str, Any]:
    text = (review_text or "").strip().lower()
    issue_map = {
        "food": ["food", "dish", "meal", "taste", "flavor", "cold", "undercooked", "overcooked"],
        "service": ["service", "server", "staff", "rude", "attitude", "host", "waiter"],
        "wait_time": ["wait", "slow", "late", "line", "queue"],
        "cleanliness": ["clean", "dirty", "messy", "smell", "hygiene"],
        "pricing": ["price", "expensive", "cost", "value", "overpriced"],
    }
    issue_tags = [tag for tag, words in issue_map.items() if any(word in text for word in words)]

    if not text:
        issue_tags.append("no_text_rating_only")
    if rating >= 4:
        issue_tags.append("positive_compliment")
    elif rating == 3:
        issue_tags.append("mixed_sentiment")
    elif rating <= 2 and not issue_tags:
        issue_tags.append("service_recovery")

    risk_flags: list[str] = []
    if rating <= 2:
        risk_flags.append("high_reputation_risk")
    if "cleanliness" in issue_tags:
        risk_flags.append("health_perception_risk")
    if "pricing" in issue_tags and rating <= 2:
        risk_flags.append("value_concern")

    if rating >= 4:
        sentiment = "positive"
    elif rating == 3:
        sentiment = "mixed"
    else:
        sentiment = "negative"

    label_map = {
        "food": "complaint about food",
        "service": "complaint about service",
        "wait_time": "wait time",
        "cleanliness": "cleanliness",
        "pricing": "pricing",
        "no_text_rating_only": "no-text rating only",
        "positive_compliment": "positive compliment",
        "mixed_sentiment": "mixed sentiment",
        "service_recovery": "service recovery",
    }
    if issue_tags:
        reason_summary = ", ".join(label_map.get(tag, tag) for tag in issue_tags[:3])
    else:
        reason_summary = "general customer feedback"

    confidence_note = (
        "High confidence from clear text and rating signals."
        if review_text and len(review_text.split()) >= 6
        else "Moderate confidence because the review has limited detail."
    )

    return {
        "sentiment": sentiment,
        "issue_tags": issue_tags,
        "risk_flags": risk_flags,
        "reason_summary": reason_summary,
        "confidence_note": confidence_note,
    }


def fallback_reply(rating: int, tone_mode: str = "gentle_professional") -> str:
    if rating >= 4:
        if tone_mode == "warm_hospitality":
            return (
                "Thank you so much for dining with us and for sharing your kind feedback. "
                "We are grateful for your support and look forward to welcoming you back soon."
            )
        if tone_mode == "premium_brand":
            return (
                "Thank you for your thoughtful review. We truly appreciate your support and "
                "look forward to serving you again for another excellent experience."
            )
        return (
            "Thank you for your kind review. We truly appreciate your support and look forward "
            "to welcoming you back again soon."
        )

    if tone_mode == "warm_hospitality":
        return (
            "Thank you for sharing your feedback. We are sorry to hear your visit did not meet "
            "expectations, and we would appreciate the chance to learn more and follow up directly."
        )
    if tone_mode == "premium_brand":
        return (
            "Thank you for taking the time to share your experience. We are sorry the visit fell "
            "short and would value the opportunity to discuss your concerns directly."
        )
    return (
        "Thank you for your feedback. We are sorry your experience did not meet expectations, "
        "and we would appreciate the chance to follow up with you directly."
    )


def _build_user_prompt(
    *,
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    tone_mode: str,
) -> str:
    tone_label = SUPPORTED_TONES.get(tone_mode, SUPPORTED_TONES["gentle_professional"])
    return (
        f"Tone mode: {tone_label}\n"
        f"Restaurant name: {restaurant_name}\n"
        f"Location: {location}\n"
        f"Review rating: {rating}/5\n"
        f"Reviewer name: {reviewer_name}\n"
        f"Review text: {review_text or '[No written comment]'}\n\n"
        "Return a JSON object with:\n"
        "- suggestion_text: one polished reply between 45 and 120 words\n"
        "- sentiment: positive | mixed | negative\n"
        "- issue_tags: array of short tags\n"
        "- risk_flags: array of short tags\n"
        "- confidence_note: one short sentence\n"
        "- reason_summary: a short phrase that describes the main issue or compliment"
    )


async def generate_reply_bundle(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    tone_mode: str = "gentle_professional",
) -> dict[str, Any]:
    bundle = classify_review(review_text, rating)
    bundle["suggestion_text"] = fallback_reply(rating, tone_mode=tone_mode)

    if not api_key:
        return bundle

    try:
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(
                        review_text=review_text,
                        rating=rating,
                        reviewer_name=reviewer_name,
                        restaurant_name=restaurant_name,
                        location=location,
                        tone_mode=tone_mode,
                    ),
                },
            ],
            temperature=0.5,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        bundle.update(
            {
                "suggestion_text": (parsed.get("suggestion_text") or bundle["suggestion_text"]).strip(),
                "sentiment": parsed.get("sentiment") or bundle["sentiment"],
                "issue_tags": parsed.get("issue_tags") or bundle["issue_tags"],
                "risk_flags": parsed.get("risk_flags") or bundle["risk_flags"],
                "confidence_note": parsed.get("confidence_note") or bundle["confidence_note"],
                "reason_summary": parsed.get("reason_summary") or bundle["reason_summary"],
            }
        )
    except Exception as exc:
        logger.error("OpenAI structured reply generation failed, using fallback: %s", exc)

    return bundle


def generate_reply_bundle_sync(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    tone_mode: str = "gentle_professional",
) -> dict[str, Any]:
    bundle = classify_review(review_text, rating)
    bundle["suggestion_text"] = fallback_reply(rating, tone_mode=tone_mode)

    if not api_key:
        return bundle

    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(
                        review_text=review_text,
                        rating=rating,
                        reviewer_name=reviewer_name,
                        restaurant_name=restaurant_name,
                        location=location,
                        tone_mode=tone_mode,
                    ),
                },
            ],
            temperature=0.5,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        bundle.update(
            {
                "suggestion_text": (parsed.get("suggestion_text") or bundle["suggestion_text"]).strip(),
                "sentiment": parsed.get("sentiment") or bundle["sentiment"],
                "issue_tags": parsed.get("issue_tags") or bundle["issue_tags"],
                "risk_flags": parsed.get("risk_flags") or bundle["risk_flags"],
                "confidence_note": parsed.get("confidence_note") or bundle["confidence_note"],
                "reason_summary": parsed.get("reason_summary") or bundle["reason_summary"],
            }
        )
    except Exception as exc:
        logger.error("OpenAI structured reply generation failed, using fallback: %s", exc)

    return bundle


async def generate_reply(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    tone_mode: str = "gentle_professional",
) -> str:
    bundle = await generate_reply_bundle(
        review_text=review_text,
        rating=rating,
        reviewer_name=reviewer_name,
        restaurant_name=restaurant_name,
        location=location,
        api_key=api_key,
        model=model,
        tone_mode=tone_mode,
    )
    return bundle["suggestion_text"]


def generate_reply_sync(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    tone_mode: str = "gentle_professional",
) -> str:
    bundle = generate_reply_bundle_sync(
        review_text=review_text,
        rating=rating,
        reviewer_name=reviewer_name,
        restaurant_name=restaurant_name,
        location=location,
        api_key=api_key,
        model=model,
        tone_mode=tone_mode,
    )
    return bundle["suggestion_text"]
