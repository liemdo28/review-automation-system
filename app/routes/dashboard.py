"""Dashboard HTML routes using Jinja2 templates."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuthSession, Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.review_ops import ReviewFilters, apply_review_filters, count_reviews, derive_review_status

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    summary = {
        "total_unreplied_reviews": await count_reviews(db),
        "google_unreplied_reviews": await count_reviews(db, platform="google"),
        "yelp_unreplied_reviews": await count_reviews(db, platform="yelp"),
        "negative_reviews_needing_attention": await count_reviews(db, negative_only=True),
        "reviews_collected_today": (
            await db.execute(select(func.count()).select_from(Review).where(Review.collected_at >= today_start))
        ).scalar()
        or 0,
        "failed_jobs": (
            await db.execute(select(func.count()).select_from(Job).where(Job.status == "failed"))
        ).scalar()
        or 0,
        "auth_expired_jobs": (
            await db.execute(
                select(func.count()).select_from(ReviewSource).where(ReviewSource.session_status == "reauth_required")
            )
        ).scalar()
        or 0,
    }

    locations = (await db.execute(select(Location).where(Location.is_active.is_(True)).order_by(Location.name))).scalars().all()
    source_items = []
    for location in locations:
        sources = (
            await db.execute(
                select(ReviewSource).where(ReviewSource.location_id == location.id).order_by(ReviewSource.platform)
            )
        ).scalars().all()
        outstanding = (
            await db.execute(
                select(func.count()).select_from(
                    apply_review_filters(
                        select(Review).where(Review.location_id == location.id),
                        ReviewFilters(location_id=location.id),
                    ).subquery()
                )
            )
        ).scalar() or 0
        source_items.append({"location": location, "sources": sources, "outstanding": outstanding})

    recent_jobs = (
        await db.execute(select(Job).order_by(desc(Job.queued_at)).limit(15))
    ).scalars().all()

    recent_reviews_query = apply_review_filters(
        select(Review),
        ReviewFilters(date_preset="7d"),
    ).order_by(Review.review_date.desc().nullslast(), Review.last_seen_at.desc())
    recent_reviews = (await db.execute(recent_reviews_query.limit(10))).scalars().all()
    recent_review_items = []
    for review in recent_reviews:
        reply = (
            await db.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        suggestion = (
            await db.execute(
                select(ReplySuggestion)
                .where(ReplySuggestion.review_id == review.id)
                .order_by(ReplySuggestion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        location = await db.get(Location, review.location_id)
        source = await db.get(ReviewSource, review.source_id) if review.source_id else None
        recent_review_items.append(
            {
                "review": review,
                "reply": reply,
                "suggestion": suggestion,
                "location": location,
                "source": source,
                "status": derive_review_status(review, reply),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "summary": summary,
            "source_items": source_items,
            "recent_jobs": recent_jobs,
            "recent_review_items": recent_review_items,
        },
    )


@router.get("/reviews")
async def reviews_page(
    request: Request,
    location_id: int | None = None,
    platform: str | None = None,
    rating: int | None = None,
    status: str | None = None,
    date_preset: str | None = "7d",
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    per_page = 25
    offset = (page - 1) * per_page

    filters = ReviewFilters(
        location_id=location_id,
        platform=platform,
        rating=rating,
        status=status,
        date_preset=date_preset,
        date_from=date_from,
        date_to=date_to,
    )
    query = apply_review_filters(select(Review), filters).order_by(
        Review.review_date.desc().nullslast(),
        Review.last_seen_at.desc(),
    )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    reviews = (await db.execute(query.limit(per_page).offset(offset))).scalars().all()
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()

    items = []
    for review in reviews:
        reply = (
            await db.execute(select(Reply).where(Reply.review_id == review.id))
        ).scalar_one_or_none()
        suggestion = (
            await db.execute(
                select(ReplySuggestion)
                .where(ReplySuggestion.review_id == review.id)
                .order_by(ReplySuggestion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_job = (
            await db.execute(select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()).limit(1))
        ).scalar_one_or_none()
        location = await db.get(Location, review.location_id)
        source = await db.get(ReviewSource, review.source_id) if review.source_id else None
        items.append(
            {
                "review": review,
                "reply": reply,
                "suggestion": suggestion,
                "location": location,
                "source": source,
                "status": derive_review_status(review, reply, latest_job),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="reviews.html",
        context={
            "request": request,
            "items": items,
            "locations": locations,
            "total": total,
            "page": page,
            "per_page": per_page,
            "filters": {
                "location_id": location_id,
                "platform": platform,
                "rating": rating,
                "status": status,
                "date_preset": date_preset,
                "date_from": date_from.isoformat() if date_from else "",
                "date_to": date_to.isoformat() if date_to else "",
            },
        },
    )


@router.get("/reviews/{review_id}")
async def review_detail(request: Request, review_id: int, db: AsyncSession = Depends(get_db)):
    review = await db.get(Review, review_id)
    if not review:
        return templates.TemplateResponse(request=request, name="404.html", context={"request": request}, status_code=404)

    reply = (
        await db.execute(select(Reply).where(Reply.review_id == review.id))
    ).scalar_one_or_none()
    suggestions = (
        await db.execute(
            select(ReplySuggestion)
            .where(ReplySuggestion.review_id == review.id)
            .order_by(ReplySuggestion.created_at.desc())
        )
    ).scalars().all()
    location = await db.get(Location, review.location_id)
    source = await db.get(ReviewSource, review.source_id) if review.source_id else None
    jobs = (
        await db.execute(select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()))
    ).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="review_detail.html",
        context={
            "request": request,
            "review": review,
            "reply": reply,
            "suggestions": suggestions,
            "location": location,
            "source": source,
            "jobs": jobs,
            "review_status": derive_review_status(review, reply, jobs[0] if jobs else None),
        },
    )


@router.get("/locations")
async def locations_page(request: Request, db: AsyncSession = Depends(get_db)):
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    items = []
    for location in locations:
        sources = (
            await db.execute(
                select(ReviewSource).where(ReviewSource.location_id == location.id).order_by(ReviewSource.platform)
            )
        ).scalars().all()
        google_count = (
            await db.execute(
                select(func.count()).select_from(
                    apply_review_filters(
                        select(Review).where(Review.location_id == location.id, Review.platform == "google"),
                        ReviewFilters(location_id=location.id, platform="google"),
                    ).subquery()
                )
            )
        ).scalar() or 0
        yelp_count = (
            await db.execute(
                select(func.count()).select_from(
                    apply_review_filters(
                        select(Review).where(Review.location_id == location.id, Review.platform == "yelp"),
                        ReviewFilters(location_id=location.id, platform="yelp"),
                    ).subquery()
                )
            )
        ).scalar() or 0
        items.append(
            {
                "loc": location,
                "sources": sources,
                "google_count": google_count,
                "yelp_count": yelp_count,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="locations.html",
        context={
            "request": request,
            "locations": items,
        },
    )


@router.get("/admin/sources")
async def admin_sources_page(request: Request, db: AsyncSession = Depends(get_db)):
    sources = (await db.execute(select(ReviewSource).order_by(ReviewSource.location_id, ReviewSource.platform))).scalars().all()
    items = []
    for source in sources:
        location = await db.get(Location, source.location_id)
        sessions = (
            await db.execute(
                select(AuthSession)
                .where(AuthSession.source_id == source.id)
                .order_by(AuthSession.updated_at.desc())
                .limit(5)
            )
        ).scalars().all()
        items.append({"source": source, "location": location, "sessions": sessions})

    return templates.TemplateResponse(
        request=request,
        name="admin_sources.html",
        context={
            "request": request,
            "items": items,
        },
    )


@router.post("/admin/sources/{source_id}")
async def admin_update_source(
    source_id: int,
    source_label: str = Form(""),
    source_url: str = Form(""),
    auth_mode: str = Form("manual_session"),
    session_status: str = Form("unknown"),
    settings_json: str = Form("{}"),
    is_active: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(ReviewSource, source_id)
    if not source:
        return RedirectResponse("/admin/sources", status_code=303)

    try:
        settings = json.loads(settings_json or "{}")
    except json.JSONDecodeError:
        settings = source.settings or {}

    source.source_label = source_label
    source.source_url = source_url
    source.auth_mode = auth_mode
    source.session_status = session_status
    source.settings = settings
    source.is_active = is_active == "on"
    await db.commit()
    return RedirectResponse("/admin/sources", status_code=303)


@router.post("/admin/sources/{source_id}/sessions")
async def admin_add_source_session(
    source_id: int,
    session_reference: str = Form(...),
    session_status: str = Form("active"),
    expires_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(ReviewSource, source_id)
    if not source:
        return RedirectResponse("/admin/sources", status_code=303)

    parsed_expiry = None
    if expires_at:
        try:
            parsed_expiry = datetime.fromisoformat(expires_at)
            if parsed_expiry.tzinfo is None:
                parsed_expiry = parsed_expiry.replace(tzinfo=timezone.utc)
        except ValueError:
            parsed_expiry = None

    auth_session = AuthSession(
        source_id=source.id,
        platform=source.platform,
        session_reference=session_reference,
        expires_at=parsed_expiry,
        last_validated_at=datetime.now(timezone.utc),
        status=session_status,
    )
    db.add(auth_session)
    source.session_status = session_status
    source.last_auth_at = datetime.now(timezone.utc)
    await db.commit()
    return RedirectResponse("/admin/sources", status_code=303)
