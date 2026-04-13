from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Review
from app.services.email_alert import send_daily_negative_review_report
from app.services.gm_report import build_daily_negative_review_report


async def main() -> None:
    async with AsyncSessionLocal() as db:
        report = await build_daily_negative_review_report(db)
        recipients: list[str] = []
        if settings.alert_email_to:
            recipients.extend([item.strip() for item in settings.alert_email_to.split(",") if item.strip()])

        sent = send_daily_negative_review_report(report.title, report.body, recipients)
        if sent and report.review_ids:
            reviews = (await db.execute(select(Review).where(Review.id.in_(report.review_ids)))).scalars().all()
            for review in reviews:
                review.gm_report_sent = True
            await db.commit()

        print(
            f"Daily negative review report {'sent' if sent else 'failed'}; "
            f"recipients={len(recipients)} reviews={report.total_reviews}"
        )


if __name__ == "__main__":
    asyncio.run(main())
