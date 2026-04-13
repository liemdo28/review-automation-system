"""Backfill audit fields for existing reviews using current classification rules."""

from __future__ import annotations

from app.database import SyncSessionLocal
from app.models import Review
from app.services.ai_reply import classify_review


def main(force: bool = False) -> None:
    session = SyncSessionLocal()
    updated = 0
    try:
        reviews = session.query(Review).all()
        for review in reviews:
            if not force and review.issue_category and review.severity_level and review.analysis_summary:
                continue
            bundle = classify_review(review.review_text or "", review.rating)
            review.is_flagged = bool(review.rating <= 3)
            review.issue_category = bundle.get("issue_category")
            review.severity_level = bundle.get("severity_level")
            review.analysis_summary = bundle.get("analysis_summary")
            if not review.is_flagged:
                review.gm_report_sent = False
            updated += 1
        session.commit()
        print(f"Backfilled audit fields for {updated} review(s).")
    finally:
        session.close()


if __name__ == "__main__":
    main()
