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
    "- Preserve the review's original language. Do not translate the guest review or your reply into a different language.\n"
    "- Keep the reply warm, human, and concise. Never sound robotic or stiff.\n"
    "- 5-star reviews should feel upbeat, grateful, and welcoming.\n"
    "- 3-4 star reviews should feel appreciative, calm, and improvement-minded.\n"
    "- 1-2 star reviews should feel empathetic, steady, and non-defensive.\n"
    "- Do not invent facts.\n"
    "- Do not argue with the customer.\n"
    "- Do not over-apologize.\n"
    "- Do not offer compensation, refunds, or discounts unless explicitly told.\n"
    "- Do not make legal admissions or promise refunds, discounts, or compensation.\n"
    "- Stay appropriate for a US restaurant brand voice.\n"
    "- Negative reviews should acknowledge the concern, protect the brand, and invite offline follow-up if needed.\n"
    "- Positive reviews should thank the guest warmly, reinforce trust, and invite them back naturally.\n"
    "- Read rating, review_text, and issue tags together. If the guest mentions food, service, price, wait time, or cleanliness, respond to that context naturally.\n"
    "- Output valid JSON with keys: suggestion_text, sentiment, issue_tags, risk_flags, confidence_note, reason_summary, issue_category, severity_level, analysis_summary."
)


def normalize_rating(raw: Any) -> int:
    if isinstance(raw, int):
        return max(1, min(5, raw))
    return STAR_MAP.get(str(raw).upper(), 0)


def classify_review(review_text: str, rating: int) -> dict[str, Any]:
    text = (review_text or "").strip().lower()
    issue_map = {
        "food": ["cold", "undercooked", "overcooked", "raw", "bland", "flavorless", "burnt", "stale"],
        "service": ["rude", "attitude", "ignored", "unfriendly", "dismissive", "hostile"],
        "wait_time": ["long wait", "waited", "slow", "late", "queue", "line", "took forever"],
        "cleanliness": ["dirty", "messy", "smell", "hygiene", "unclean", "filthy"],
        "pricing": ["expensive", "cost too much", "overpriced", "ripoff", "too pricey"],
        "staff_attitude": ["manager was rude", "server was rude", "bartender was rude", "host was rude", "attitude"],
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

    positive_only_tags = {"positive_compliment", "no_text_rating_only"}
    issue_category = issue_tags[0] if issue_tags else ("positive_compliment" if rating >= 4 else "general_feedback")
    severity_level = "low"
    if rating >= 4 and set(issue_tags).issubset(positive_only_tags):
        severity_level = "low"
    elif rating <= 2 or "cleanliness" in issue_tags:
        severity_level = "high"
    elif rating == 3 or any(tag not in positive_only_tags for tag in issue_tags):
        severity_level = "medium"

    label_map = {
        "food": "complaint about food",
        "service": "complaint about service",
        "wait_time": "wait time",
        "cleanliness": "cleanliness",
        "pricing": "pricing",
        "staff_attitude": "staff attitude",
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

    if rating <= 3:
        analysis_summary = (
            f"Flagged for audit because this is a {rating}-star review. Primary issue: {label_map.get(issue_category, issue_category)}. "
            f"Severity is {severity_level}. Suggested handling: {'contact customer' if severity_level == 'high' else 'reply only'}."
        )
    else:
        analysis_summary = (
            f"Positive review with primary theme: {label_map.get(issue_category, issue_category)} and low operational risk."
        )

    return {
        "sentiment": sentiment,
        "issue_tags": issue_tags,
        "risk_flags": risk_flags,
        "reason_summary": reason_summary,
        "confidence_note": confidence_note,
        "issue_category": issue_category,
        "severity_level": severity_level,
        "analysis_summary": analysis_summary,
    }


def sanitize_review_signals(
    review_text: str,
    rating: int,
    *,
    issue_tags: list[str] | None = None,
    risk_flags: list[str] | None = None,
    sentiment: str | None = None,
    reason_summary: str | None = None,
    issue_category: str | None = None,
    severity_level: str | None = None,
    analysis_summary: str | None = None,
    confidence_note: str | None = None,
) -> dict[str, Any]:
    baseline = classify_review(review_text, rating)
    normalized = {
        "sentiment": sentiment or baseline["sentiment"],
        "issue_tags": list(issue_tags or baseline["issue_tags"] or []),
        "risk_flags": list(risk_flags or baseline["risk_flags"] or []),
        "reason_summary": reason_summary or baseline["reason_summary"],
        "issue_category": issue_category or baseline["issue_category"],
        "severity_level": severity_level or baseline["severity_level"],
        "analysis_summary": analysis_summary or baseline["analysis_summary"],
        "confidence_note": confidence_note or baseline["confidence_note"],
    }

    negative_tags = {"food", "service", "wait_time", "cleanliness", "pricing", "staff_attitude", "service_recovery"}
    positive_only_tags = {"positive_compliment", "no_text_rating_only"}
    baseline_tags = set(baseline.get("issue_tags") or [])
    normalized_tags = [str(tag).strip().lower() for tag in normalized["issue_tags"] if str(tag).strip()]
    normalized_risk_flags = [str(flag).strip().lower() for flag in normalized["risk_flags"] if str(flag).strip()]

    if rating >= 5 and not (baseline_tags & negative_tags):
        normalized_tags = [tag for tag in normalized_tags if tag not in negative_tags]
        if "positive_compliment" not in normalized_tags:
            normalized_tags.append("positive_compliment")
        normalized_risk_flags = []
        normalized["sentiment"] = "positive"
        normalized["issue_category"] = "positive_compliment"
        normalized["severity_level"] = "low"
        normalized["reason_summary"] = "positive compliment"
        normalized["analysis_summary"] = "Positive review with clear praise and low operational risk."
    elif rating == 4 and not (baseline_tags & negative_tags):
        normalized_tags = [tag for tag in normalized_tags if tag not in negative_tags]
        if "positive_compliment" not in normalized_tags:
            normalized_tags.append("positive_compliment")
        if set(normalized_tags).issubset(positive_only_tags):
            normalized["sentiment"] = "positive"
            normalized["issue_category"] = "positive_compliment"
            normalized["severity_level"] = "low"
            normalized["reason_summary"] = "positive compliment"
            normalized["analysis_summary"] = "Positive review with clear praise and low operational risk."

    if rating <= 3:
        normalized["issue_category"] = baseline["issue_category"]
        normalized["severity_level"] = baseline["severity_level"]
        normalized["analysis_summary"] = baseline["analysis_summary"]

    normalized["issue_tags"] = normalized_tags
    normalized["risk_flags"] = normalized_risk_flags
    return normalized


def normalize_generated_bundle(review_text: str, rating: int, bundle: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(bundle)
    normalized.update(
        sanitize_review_signals(
            review_text,
            rating,
            issue_tags=normalized.get("issue_tags"),
            risk_flags=normalized.get("risk_flags"),
            sentiment=normalized.get("sentiment"),
            reason_summary=normalized.get("reason_summary"),
            issue_category=normalized.get("issue_category"),
            severity_level=normalized.get("severity_level"),
            analysis_summary=normalized.get("analysis_summary"),
            confidence_note=normalized.get("confidence_note"),
        )
    )
    return normalized


def fallback_reply(rating: int, tone_mode: str = "gentle_professional") -> str:
    if rating >= 4:
        if tone_mode == "warm_hospitality":
            return (
                "Thank you so much for spending time with us and for sharing such kind feedback. "
                "We are really glad you had a good visit, and we would love to welcome you back again soon."
            )
        if tone_mode == "premium_brand":
            return (
                "Thank you for your thoughtful review. We truly appreciate your support and are delighted to know the visit left a strong impression. "
                "We look forward to welcoming you back again soon."
            )
        return (
            "Thank you so much for your kind review. We are very happy to hear you enjoyed your visit, "
            "and we look forward to welcoming you back again soon."
        )

    if rating == 3:
        return (
            "Thank you for taking the time to share your feedback. We appreciate hearing about your visit "
            "and will use your comments to keep improving both the food and the service experience."
        )

    if tone_mode == "warm_hospitality":
        return (
            "Thank you for sharing your feedback with us. We are sorry to hear your visit did not feel as it should have, "
            "and we would appreciate the chance to learn more and follow up directly."
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
        "Keep the reply in the same language as the review text when a language is evident. Do not translate.\n"
        "Return a JSON object with:\n"
        "- suggestion_text: one polished reply between 45 and 120 words\n"
        "- sentiment: positive | mixed | negative\n"
        "- issue_tags: array of short tags\n"
        "- risk_flags: array of short tags\n"
        "- confidence_note: one short sentence\n"
        "- reason_summary: a short phrase that describes the main issue or compliment\n"
        "- issue_category: one of food | service | wait_time | cleanliness | pricing | staff_attitude | no_text_rating_only | positive_compliment | mixed_sentiment | general_feedback\n"
        "- severity_level: low | medium | high\n"
        "- analysis_summary: one short operational summary sentence"
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
                "issue_category": parsed.get("issue_category") or bundle["issue_category"],
                "severity_level": parsed.get("severity_level") or bundle["severity_level"],
                "analysis_summary": parsed.get("analysis_summary") or bundle["analysis_summary"],
            }
        )
    except Exception as exc:
        logger.error("OpenAI structured reply generation failed, using fallback: %s", exc)

    return normalize_generated_bundle(review_text, rating, bundle)


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
                "issue_category": parsed.get("issue_category") or bundle["issue_category"],
                "severity_level": parsed.get("severity_level") or bundle["severity_level"],
                "analysis_summary": parsed.get("analysis_summary") or bundle["analysis_summary"],
            }
        )
    except Exception as exc:
        logger.error("OpenAI structured reply generation failed, using fallback: %s", exc)

    return normalize_generated_bundle(review_text, rating, bundle)


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
