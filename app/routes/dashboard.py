"""Dashboard HTML routes using Jinja2 templates."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Location, Review, Reply, Job, FetchLog,
    ReviewAnalysis, ReviewAction,
)

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    total_reviews = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    total_posted = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "posted")
    )).scalar() or 0
    total_pending = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "awaiting_approval")
    )).scalar() or 0
    total_escalated = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "escalated")
    )).scalar() or 0
    total_sensitive = (await db.execute(
        select(func.count()).select_from(Review).where(Review.is_sensitive == True)  # noqa: E712
    )).scalar() or 0
    total_suggested = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "suggested")
    )).scalar() or 0
    queued_jobs = (await db.execute(
        select(func.count()).select_from(Job).where(Job.status == "queued")
    )).scalar() or 0

    locations = (await db.execute(
        select(Location).where(Location.is_active == True)  # noqa: E712
    )).scalars().all()
    loc_data = []
    for loc in locations:
        rc = (await db.execute(
            select(func.count()).select_from(Review).where(Review.location_id == loc.id)
        )).scalar() or 0
        last_fetch = (await db.execute(
            select(FetchLog.fetched_at).where(FetchLog.location_id == loc.id)
            .order_by(desc(FetchLog.fetched_at)).limit(1)
        )).scalar()
        loc_data.append({"loc": loc, "review_count": rc, "last_fetch": last_fetch})

    recent_jobs = (await db.execute(
        select(Job).order_by(desc(Job.queued_at)).limit(15)
    )).scalars().all()

    urgent_reviews = (await db.execute(
        select(Review).where(
            Review.status.in_(["escalated", "awaiting_approval"])
        ).order_by(Review.is_sensitive.desc(), desc(Review.fetched_at)).limit(10)
    )).scalars().all()
    urgent_items = []
    for r in urgent_reviews:
        loc = await db.get(Location, r.location_id)
        urgent_items.append({"review": r, "location": loc})

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_reviews": total_reviews,
        "total_posted": total_posted,
        "total_pending": total_pending,
        "total_escalated": total_escalated,
        "total_sensitive": total_sensitive,
        "total_suggested": total_suggested,
        "queued_jobs": queued_jobs,
        "locations": loc_data,
        "recent_jobs": recent_jobs,
        "urgent_items": urgent_items,
    })


@router.get("/reviews")
async def reviews_page(
    request: Request,
    location_id: int | None = None,
    platform: str | None = None,
    rating: int | None = None,
    status: str | None = None,
    urgency: str | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    per_page = 25
    offset = (page - 1) * per_page

    query = select(Review).order_by(desc(Review.fetched_at))
    if location_id:
        query = query.where(Review.location_id == location_id)
    if platform:
        query = query.where(Review.platform == platform)
    if rating:
        query = query.where(Review.rating == rating)
    if status:
        query = query.where(Review.status == status)
    if urgency:
        query = query.where(Review.urgency == urgency)

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0

    reviews = (await db.execute(query.limit(per_page).offset(offset))).scalars().all()

    items = []
    for r in reviews:
        reply = (await db.execute(
            select(Reply).where(Reply.review_id == r.id)
        )).scalar_one_or_none()
        loc = await db.get(Location, r.location_id)
        items.append({"review": r, "reply": reply, "location": loc})

    locations_all = (await db.execute(select(Location))).scalars().all()

    return templates.TemplateResponse("reviews.html", {
        "request": request,
        "items": items,
        "locations": locations_all,
        "total": total,
        "page": page,
        "per_page": per_page,
        "filters": {
            "location_id": location_id, "platform": platform,
            "rating": rating, "status": status, "urgency": urgency,
        },
    })


@router.get("/reviews/{review_id}")
async def review_detail(request: Request, review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    reply = (await db.execute(
        select(Reply).where(Reply.review_id == review.id)
    )).scalar_one_or_none()
    location = await db.get(Location, review.location_id)
    analysis = (await db.execute(
        select(ReviewAnalysis).where(ReviewAnalysis.review_id == review.id)
    )).scalar_one_or_none()
    jobs = (await db.execute(
        select(Job).where(Job.review_id == review.id).order_by(Job.queued_at)
    )).scalars().all()
    actions = (await db.execute(
        select(ReviewAction).where(ReviewAction.review_id == review.id)
        .order_by(ReviewAction.performed_at.asc())
    )).scalars().all()

    return templates.TemplateResponse("review_detail.html", {
        "request": request,
        "review": review,
        "reply": reply,
        "location": location,
        "analysis": analysis,
        "jobs": jobs,
        "actions": actions,
    })


@router.get("/metrics")
async def metrics_page(request: Request, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    total = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    new_today = (await db.execute(
        select(func.count()).select_from(Review).where(Review.fetched_at >= day_ago)
    )).scalar() or 0
    new_week = (await db.execute(
        select(func.count()).select_from(Review).where(Review.fetched_at >= week_ago)
    )).scalar() or 0
    auto_replied = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "auto_replied")
    )).scalar() or 0
    escalated = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "escalated")
    )).scalar() or 0
    awaiting = (await db.execute(
        select(func.count()).select_from(Review).where(Review.status == "awaiting_approval")
    )).scalar() or 0
    sensitive = (await db.execute(
        select(func.count()).select_from(Review).where(Review.is_sensitive == True)  # noqa: E712
    )).scalar() or 0

    avg_rating = (await db.execute(
        select(func.avg(Review.rating)).select_from(Review)
    )).scalar()

    sentiments: dict = {}
    for s in ["positive", "neutral", "negative", "mixed"]:
        cnt = (await db.execute(
            select(func.count()).select_from(Review).where(Review.sentiment == s)
        )).scalar() or 0
        sentiments[s] = cnt

    analyses = (await db.execute(
        select(ReviewAnalysis.issue_types_json)
        .where(ReviewAnalysis.issue_types_json.isnot(None))
        .limit(500)
    )).scalars().all()
    issue_counts: dict[str, int] = {}
    for issue_list in analyses:
        if isinstance(issue_list, list):
            for issue in issue_list:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
    top_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    platforms: dict = {}
    for p in ["google", "yelp"]:
        cnt = (await db.execute(
            select(func.count()).select_from(Review).where(Review.platform == p)
        )).scalar() or 0
        platforms[p] = cnt

    return templates.TemplateResponse("metrics.html", {
        "request": request,
        "total": total,
        "new_today": new_today,
        "new_week": new_week,
        "auto_replied": auto_replied,
        "escalated": escalated,
        "awaiting": awaiting,
        "sensitive": sensitive,
        "avg_rating": round(float(avg_rating), 2) if avg_rating else 0,
        "sentiments": sentiments,
        "platforms": platforms,
        "top_issues": top_issues,
        "auto_reply_rate": round(auto_replied / total * 100, 1) if total else 0,
    })


@router.get("/locations")
async def locations_page(request: Request, db: AsyncSession = Depends(get_db)):
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()

    loc_data = []
    for loc in locations:
        google_count = (await db.execute(
            select(func.count()).select_from(Review).where(
                and_(Review.location_id == loc.id, Review.platform == "google")
            )
        )).scalar() or 0
        yelp_count = (await db.execute(
            select(func.count()).select_from(Review).where(
                and_(Review.location_id == loc.id, Review.platform == "yelp")
            )
        )).scalar() or 0
        last_fetch = (await db.execute(
            select(FetchLog.fetched_at).where(FetchLog.location_id == loc.id)
            .order_by(desc(FetchLog.fetched_at)).limit(1)
        )).scalar()
        loc_data.append({
            "loc": loc, "google_count": google_count,
            "yelp_count": yelp_count, "last_fetch": last_fetch,
        })

    return templates.TemplateResponse("locations.html", {
        "request": request,
        "locations": loc_data,
    })
