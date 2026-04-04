"""AI reply generation using OpenAI."""
import logging
import openai
from typing import Any

logger = logging.getLogger("review_system.ai_reply")

STAR_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

SYSTEM_PROMPT = (
    "You are a restaurant owner support assistant.\n"
    "Write short, professional, warm, natural Google review replies for a restaurant.\n"
    "Rules:\n"
    "- Keep reply between 40 and 120 words.\n"
    "- Sound human, polite, and concise.\n"
    "- Never mention AI.\n"
    "- Do not invent facts.\n"
    "- Do not offer discounts unless explicitly provided.\n"
    "- For negative reviews (1-3 stars), apologize briefly, acknowledge the issue, "
    "and invite the customer to contact the restaurant privately.\n"
    "- For positive reviews (4-5 stars), thank them and mention looking forward "
    "to serving them again.\n"
    "- Output plain text only."
)


def normalize_rating(raw: Any) -> int:
    if isinstance(raw, int):
        return max(1, min(5, raw))
    return STAR_MAP.get(str(raw).upper(), 0)


def fallback_reply(rating: int) -> str:
    if rating >= 4:
        return (
            "Thank you so much for your kind review! We truly appreciate your support "
            "and look forward to serving you again soon."
        )
    return (
        "Thank you for your feedback. We are sorry your experience did not fully meet expectations. "
        "Please contact us directly so we can learn more and work to make it right."
    )


async def generate_reply(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> str:
    stars = "\u2b50" * rating
    user_prompt = (
        f"Restaurant name: {restaurant_name}\n"
        f"Location: {location}\n"
        f"Review rating: {stars}\n"
        f"Reviewer name: {reviewer_name}\n"
        f"Review text: {review_text or '[No written comment]'}\n\n"
        "Write a reply suitable for Google Business Profile."
    )

    if not api_key:
        return fallback_reply(rating)

    try:
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        text = resp.choices[0].message.content or ""
        return text.strip()
    except Exception as e:
        logger.error(f"OpenAI call failed, using fallback: {e}")
        return fallback_reply(rating)


def generate_reply_sync(
    review_text: str,
    rating: int,
    reviewer_name: str,
    restaurant_name: str,
    location: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> str:
    """Synchronous version for rq workers."""
    stars = "\u2b50" * rating
    user_prompt = (
        f"Restaurant name: {restaurant_name}\n"
        f"Location: {location}\n"
        f"Review rating: {stars}\n"
        f"Reviewer name: {reviewer_name}\n"
        f"Review text: {review_text or '[No written comment]'}\n\n"
        "Write a reply suitable for Google Business Profile."
    )

    if not api_key:
        return fallback_reply(rating)

    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        text = resp.choices[0].message.content or ""
        return text.strip()
    except Exception as e:
        logger.error(f"OpenAI call failed, using fallback: {e}")
        return fallback_reply(rating)
