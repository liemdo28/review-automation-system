"""Build daily negative review reports for GM visibility."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location, Review


@dataclass(slots=True)
class DailyNegativeReport:
    title: str
    report_date: str
    total_reviews: int
    by_store: dict[str, int]
    by_issue_type: dict[str, int]
    serious_issues: list[dict]
    suggested_actions: list[str]
    review_ids: list[int]
    body: str


async def build_daily_negative_review_report(
    db: AsyncSession,
    *,
    report_for: date | None = None,
) -> DailyNegativeReport:
    target_date = report_for or datetime.utcnow().date()
    start = datetime.combine(target_date, time.min)
    end = datetime.combine(target_date, time.max)

    rows = (
        await db.execute(
            select(Review, Location)
            .join(Location, Location.id == Review.location_id)
            .where(
                Review.rating <= 3,
                Review.review_date.is_not(None),
                Review.review_date >= start,
                Review.review_date <= end,
            )
            .order_by(Review.severity_level.desc().nullslast(), Review.review_date.desc().nullslast(), Review.id.desc())
        )
    ).all()

    store_counter: Counter[str] = Counter()
    issue_counter: Counter[str] = Counter()
    serious_issues: list[dict] = []
    review_ids: list[int] = []

    for review, location in rows:
        store_name = location.name if location else "Unknown store"
        issue = review.issue_category or "general_feedback"
        store_counter[store_name] += 1
        issue_counter[issue] += 1
        review_ids.append(review.id)
        if review.severity_level == "high":
            serious_issues.append(
                {
                    "review_id": review.id,
                    "store": store_name,
                    "reviewer_name": review.reviewer_name or "Anonymous",
                    "issue_category": issue,
                    "severity_level": review.severity_level,
                    "analysis_summary": review.analysis_summary or review.auto_reply_decision_reason or "Needs manual follow-up.",
                }
            )

    suggested_actions: list[str] = []
    if serious_issues:
        suggested_actions.append("Review all high-severity items first and decide whether direct guest follow-up is needed.")
    if issue_counter.get("service", 0) or issue_counter.get("staff_attitude", 0):
        suggested_actions.append("Coach the shift team on service recovery and staff tone for the next service window.")
    if issue_counter.get("food", 0) or issue_counter.get("cleanliness", 0):
        suggested_actions.append("Inspect kitchen execution and cleanliness issues before the next peak period.")
    if issue_counter.get("wait_time", 0):
        suggested_actions.append("Check labor coverage and ticket pacing for wait time complaints.")
    if not suggested_actions:
        suggested_actions.append("Use the dashboard queue to review and close the flagged reviews.")

    title = "Daily Negative Review Report"
    lines = [
        title,
        f"Date: {target_date.isoformat()}",
        "",
        f"Total negative reviews (<= 3 stars): {len(rows)}",
        "",
        "Breakdown by store:",
    ]
    if store_counter:
        lines.extend(f"- {store}: {count}" for store, count in store_counter.most_common())
    else:
        lines.append("- No negative reviews collected for this date.")

    lines.extend(["", "Breakdown by issue type:"])
    if issue_counter:
        lines.extend(f"- {issue}: {count}" for issue, count in issue_counter.most_common())
    else:
        lines.append("- No issue categories recorded.")

    lines.extend(["", "Top serious issues:"])
    if serious_issues:
        for issue in serious_issues[:10]:
            lines.append(
                f"- {issue['store']} / {issue['reviewer_name']} / {issue['issue_category']}: {issue['analysis_summary']}"
            )
    else:
        lines.append("- No high-severity issues today.")

    lines.extend(["", "Suggested actions:"])
    lines.extend(f"- {item}" for item in suggested_actions)

    return DailyNegativeReport(
        title=title,
        report_date=target_date.isoformat(),
        total_reviews=len(rows),
        by_store=dict(store_counter),
        by_issue_type=dict(issue_counter),
        serious_issues=serious_issues,
        suggested_actions=suggested_actions,
        review_ids=review_ids,
        body="\n".join(lines),
    )
