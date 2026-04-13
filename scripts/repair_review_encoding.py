from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Reply, ReplySuggestion, Review
from app.providers.base import ReviewProvider


def _repair(value: str | None) -> str | None:
    return ReviewProvider.normalize_text(value)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        review_rows = (await session.execute(select(Review))).scalars().all()
        reply_rows = (await session.execute(select(Reply))).scalars().all()
        suggestion_rows = (await session.execute(select(ReplySuggestion))).scalars().all()

        updated = 0
        for review in review_rows:
            original = (
                review.reviewer_name,
                review.review_text,
                review.detected_owner_reply_text,
            )
            review.reviewer_name = _repair(review.reviewer_name)
            review.review_text = _repair(review.review_text)
            review.detected_owner_reply_text = _repair(review.detected_owner_reply_text)
            if original != (review.reviewer_name, review.review_text, review.detected_owner_reply_text):
                updated += 1

        for reply in reply_rows:
            original = (reply.ai_reply_text, reply.reason_summary, reply.confidence_note)
            reply.ai_reply_text = _repair(reply.ai_reply_text)
            reply.reason_summary = _repair(reply.reason_summary)
            reply.confidence_note = _repair(reply.confidence_note)
            if original != (reply.ai_reply_text, reply.reason_summary, reply.confidence_note):
                updated += 1

        for suggestion in suggestion_rows:
            original = (suggestion.suggestion_text, suggestion.reason_summary, suggestion.confidence_note)
            suggestion.suggestion_text = _repair(suggestion.suggestion_text)
            suggestion.reason_summary = _repair(suggestion.reason_summary)
            suggestion.confidence_note = _repair(suggestion.confidence_note)
            if original != (suggestion.suggestion_text, suggestion.reason_summary, suggestion.confidence_note):
                updated += 1

        await session.commit()
        print({"updated_records": updated})


if __name__ == "__main__":
    asyncio.run(main())
