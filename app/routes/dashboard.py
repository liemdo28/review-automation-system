"""Dashboard HTML routes using Jinja2 templates."""
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Location, Review, Reply, Job, FetchLog

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    total_reviews = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    total_posted = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "posted")
    )).scalar() or 0
    total_pending = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status.in_(["pending", "email_sent"]))
    )).scalar() or 0
    total_suggested = (await db.execute(
        select(func.count()).select_from(Reply).where(Reply.status == "suggested")
    )).scalar() or 0
    queued_jobs = (await db.execute(
        select(func.count()).select_from(Job).where(Job.status == "queued")
    )).scalar() or 0

    # Per location
    locations = (await db.execute(select(Location).where(Location.is_active == True))).scalars().all()  # noqa: E712
    loc_data = []
    for loc in locations:
        rc = (await db.execute(
            select(func.count()).select_from(Review).where(Review.location_id == loc.id)
        )).scalar() or 0
        last_fetch = (await db.execute(
            select(FetchLog.fetched_at)
            .where(FetchLog.location_id == loc.id)
            .order_by(desc(FetchLog.fetched_at))
            .limit(1)
        )).scalar()
        loc_data.append({"loc": loc, "review_count": rc, "last_fetch": last_fetch})

    # Recent activity
    recent_jobs = (await db.execute(
        select(Job).order_by(desc(Job.queued_at)).limit(15)
    )).scalars().all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_reviews": total_reviews,
        "total_posted": total_posted,
        "total_pending": total_pending,
        "total_suggested": total_suggested,
        "queued_jobs": queued_jobs,
        "locations": loc_data,
        "recent_jobs": recent_jobs,
    })


@router.get("/reviews")
async def reviews_page(
    request: Request,
    location_id: int | None = None,
    platform: str | None = None,
    rating: int | None = None,
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

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0

    reviews = (await db.execute(query.limit(per_page).offset(offset))).scalars().all()

    # Load replies and locations
    items = []
    for r in reviews:
        reply = (await db.execute(
            select(Reply).where(Reply.review_id == r.id)
        )).scalar_one_or_none()
        loc = await db.get(Location, r.location_id)
        items.append({"review": r, "reply": reply, "location": loc})

    locations = (await db.execute(select(Location))).scalars().all()

    return templates.TemplateResponse("reviews.html", {
        "request": request,
        "items": items,
        "locations": locations,
        "total": total,
        "page": page,
        "per_page": per_page,
        "filters": {"location_id": location_id, "platform": platform, "rating": rating},
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

    jobs = (await db.execute(
        select(Job).where(Job.review_id == review.id).order_by(Job.queued_at)
    )).scalars().all()

    return templates.TemplateResponse("review_detail.html", {
        "request": request,
        "review": review,
        "reply": reply,
        "location": location,
        "jobs": jobs,
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
