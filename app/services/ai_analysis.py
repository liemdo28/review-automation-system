"""
AI Analysis Service
===================
Produces a fully structured JSON analysis of each review, including:
- sentiment, issue_types, urgency
- manager_attention_required, auto_reply_allowed
- summary (internal) and suggested_reply (customer-facing)

Uses two separate prompts:
  A. ANALYSIS PROMPT  – classify the review
  B. REPLY PROMPT     – generate brand-tone reply (only after rule engine confirms)

Prompt version is embedded so every DB row is traceable to the exact prompt used.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import openai

logger = logging.getLogger("review_system.ai_analysis")

PROMPT_VERSION = "v2"  # bump whenever prompts change

ISSUE_TYPES = [
    "food_quality", "service", "speed", "cleanliness", "pricing",
    "atmosphere", "order_accuracy", "delivery", "staff_behavior", "other",
]

# ── Prompt A: Review Analysis ─────────────────────────────────────────────────

ANALYSIS_SYSTEM_PROMPT = """You are a restaurant review analyst. Analyze the customer review and return ONLY valid JSON.

Output schema (no markdown, no explanation, no code fences):
{
  "sentiment": "<positive|neutral|negative|mixed>",
  "issue_types": ["<one or more from: food_quality, service, speed, cleanliness, pricing, atmosphere, order_accuracy, delivery, staff_behavior, other>"],
  "urgency": "<low|medium|high>",
  "reply_recommended": <true|false>,
  "auto_reply_allowed": <true|false>,
  "manager_attention_required": <true|false>,
  "summary": "<concise 1-2 sentence internal summary>",
  "suggested_reply": "<polished customer-facing reply, 40-120 words>"
}

Rules:
- Set urgency=high and manager_attention_required=true if the review contains or implies any of:
  food poisoning, got sick, allergy, uncooked/raw food, unsafe food, rude staff, discrimination,
  racism, refund demand, charged twice, billing issue, contamination, insect, hair, dirty,
  harassment, threats, violence, lawsuit, legal action, police.
- Set auto_reply_allowed=false whenever manager_attention_required=true.
- Set auto_reply_allowed=false for all Yelp reviews (enforced by rule engine too).
- Keep summary concise and factual—do not invent facts not present in the review.
- The suggested_reply must be professional, polite, warm, concise, and brand-safe:
  * Never admit legal liability
  * Never promise refund or compensation automatically
  * Never argue with the customer
  * Never mention internal operations
  * For negative/sensitive reviews: acknowledge concern, invite offline contact
  * For positive reviews: warm thank-you, invite return visit
- Output ONLY the JSON object. No preamble, no trailing text."""


def _build_analysis_user_prompt(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    platform: str,
) -> str:
    stars = "★" * rating + "☆" * (5 - rating)
    return (
        f"Restaurant: {restaurant_name} ({location})\n"
        f"Platform: {platform}\n"
        f"Reviewer: {reviewer_name}\n"
        f"Rating: {stars} ({rating}/5)\n"
        f"Review text: {review_text or '[No written comment]'}\n\n"
        "Analyze this review and return the JSON object."
    )


# ── JSON repair / extraction ──────────────────────────────────────────────────

def _extract_json(raw: str) -> dict[str, Any]:
    """Extract JSON from model output, even if wrapped in code fences."""
    raw = raw.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    return json.loads(raw)


def _validate_analysis(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate analysis fields; fill safe defaults on missing keys."""
    valid_sentiments = {"positive", "neutral", "negative", "mixed"}
    valid_urgencies = {"low", "medium", "high"}

    sentiment = str(data.get("sentiment", "neutral")).lower()
    if sentiment not in valid_sentiments:
        sentiment = "neutral"

    urgency = str(data.get("urgency", "low")).lower()
    if urgency not in valid_urgencies:
        urgency = "low"

    raw_issues = data.get("issue_types", [])
    issue_types = [i for i in raw_issues if i in ISSUE_TYPES]
    if not issue_types:
        issue_types = ["other"]

    return {
        "sentiment": sentiment,
        "issue_types": issue_types,
        "urgency": urgency,
        "reply_recommended": bool(data.get("reply_recommended", True)),
        "auto_reply_allowed": bool(data.get("auto_reply_allowed", False)),
        "manager_attention_required": bool(data.get("manager_attention_required", False)),
        "summary": str(data.get("summary", "")).strip()[:1000],
        "suggested_reply": str(data.get("suggested_reply", "")).strip(),
    }


# ── Fallback analysis (when AI unavailable) ───────────────────────────────────

def _fallback_analysis(rating: int, platform: str) -> dict[str, Any]:
    """Generate a safe conservative analysis without calling the AI."""
    if rating >= 4:
        sentiment = "positive"
        urgency = "low"
        auto_reply = platform == "google"
        manager = False
        summary = f"Customer left a {rating}-star review."
        reply = (
            "Thank you so much for your kind words! We truly appreciate your support "
            "and look forward to welcoming you back soon."
        )
    elif rating == 3:
        sentiment = "neutral"
        urgency = "medium"
        auto_reply = False
        manager = True
        summary = f"Customer left a {rating}-star review. Manager review recommended."
        reply = (
            "Thank you for taking the time to share your feedback. "
            "We appreciate your input and are always working to improve. "
            "We hope to serve you better on your next visit."
        )
    else:
        sentiment = "negative"
        urgency = "high"
        auto_reply = False
        manager = True
        summary = f"Customer left a {rating}-star negative review. Immediate attention required."
        reply = (
            "We sincerely apologize that your experience did not meet expectations. "
            "Please contact us directly so we can learn more and make this right. "
            "Your feedback is very important to us."
        )

    return {
        "sentiment": sentiment,
        "issue_types": ["other"],
        "urgency": urgency,
        "reply_recommended": True,
        "auto_reply_allowed": auto_reply,
        "manager_attention_required": manager,
        "summary": summary,
        "suggested_reply": reply,
    }


# ── Main sync analysis function (used by rq workers) ─────────────────────────

def analyze_review_sync(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    platform: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> tuple[dict[str, Any], str]:
    """
    Perform full structured AI analysis.
    Returns (analysis_dict, raw_response_str).
    Falls back to conservative defaults on any failure.
    """
    if not api_key:
        fallback = _fallback_analysis(rating, platform)
        return fallback, json.dumps({"fallback": True, "reason": "no_api_key"})

    user_prompt = _build_analysis_user_prompt(
        review_text, rating, reviewer_name, restaurant_name, location, platform
    )

    raw_response = ""
    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,   # low temp for consistent structured output
            max_tokens=600,
            response_format={"type": "json_object"} if _supports_json_mode(model) else None,
        )
        raw_response = resp.choices[0].message.content or ""
        data = _extract_json(raw_response)
        return _validate_analysis(data), raw_response

    except json.JSONDecodeError:
        logger.warning("AI returned invalid JSON; attempting repair")
        # Retry once with explicit repair instruction
        try:
            repair_prompt = (
                f"The following text should be valid JSON but is not. "
                f"Return ONLY corrected JSON:\n{raw_response}"
            )
            client = openai.OpenAI(api_key=api_key)
            resp2 = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": repair_prompt}],
                temperature=0,
                max_tokens=600,
            )
            raw_response = resp2.choices[0].message.content or ""
            data = _extract_json(raw_response)
            return _validate_analysis(data), raw_response
        except Exception as e2:
            logger.error(f"JSON repair failed: {e2}; using fallback analysis")
            fallback = _fallback_analysis(rating, platform)
            return fallback, json.dumps({"fallback": True, "reason": "json_repair_failed", "raw": raw_response[:500]})

    except Exception as e:
        logger.error(f"AI analysis failed: {e}; using fallback")
        fallback = _fallback_analysis(rating, platform)
        return fallback, json.dumps({"fallback": True, "reason": str(e)[:200]})


# ── Async version (for FastAPI routes) ───────────────────────────────────────

async def analyze_review_async(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    platform: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> tuple[dict[str, Any], str]:
    """Async version of analyze_review_sync for FastAPI endpoints."""
    if not api_key:
        fallback = _fallback_analysis(rating, platform)
        return fallback, json.dumps({"fallback": True, "reason": "no_api_key"})

    user_prompt = _build_analysis_user_prompt(
        review_text, rating, reviewer_name, restaurant_name, location, platform
    )

    raw_response = ""
    try:
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=600,
            response_format={"type": "json_object"} if _supports_json_mode(model) else None,
        )
        raw_response = resp.choices[0].message.content or ""
        data = _extract_json(raw_response)
        return _validate_analysis(data), raw_response

    except json.JSONDecodeError:
        logger.warning("AI returned invalid JSON on async call; using fallback")
        fallback = _fallback_analysis(rating, platform)
        return fallback, json.dumps({"fallback": True, "reason": "invalid_json", "raw": raw_response[:500]})

    except Exception as e:
        logger.error(f"Async AI analysis failed: {e}")
        fallback = _fallback_analysis(rating, platform)
        return fallback, json.dumps({"fallback": True, "reason": str(e)[:200]})


def _supports_json_mode(model: str) -> bool:
    """Check if the model supports response_format json_object."""
    return any(m in model for m in ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo-1106"])
