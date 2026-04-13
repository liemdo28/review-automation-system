"""Dashboard HTML routes using Jinja2 templates."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuthSession, Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.review_ops import ReviewFilters, apply_review_filters, count_reviews, derive_review_status
from app.services.session_resolution import (
    build_shared_key,
    effective_source_url,
    is_shared_session,
    normalize_source_url_override,
    normalize_share_scope,
    resolve_auth_session_for_source,
)
from app.services.review_views import count_review_listing, fetch_review_listing

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    return int(value) if value else None


def _optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    value = value.strip()
    return date.fromisoformat(value) if value else None


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
    location_ids = [location.id for location in locations]
    all_sources = (
        await db.execute(
            select(ReviewSource)
            .where(ReviewSource.location_id.in_(location_ids))
            .order_by(ReviewSource.location_id, ReviewSource.platform, ReviewSource.id)
        )
    ).scalars().all() if location_ids else []
    sources_by_location: dict[int, list[ReviewSource]] = defaultdict(list)
    for source in all_sources:
        sources_by_location[source.location_id].append(source)

    outstanding_rows = (
        await db.execute(
            apply_review_filters(
                select(Review.location_id, func.count().label("outstanding")).group_by(Review.location_id),
                ReviewFilters(),
            )
        )
    ).all()
    outstanding_by_location = {location_id: outstanding for location_id, outstanding in outstanding_rows}

    source_items = [
        {
            "location": location,
            "sources": sources_by_location.get(location.id, []),
            "outstanding": outstanding_by_location.get(location.id, 0),
        }
        for location in locations
    ]

    recent_jobs = (
        await db.execute(select(Job).order_by(desc(Job.queued_at)).limit(15))
    ).scalars().all()

    recent_review_items = await fetch_review_listing(
        db,
        filters=ReviewFilters(date_preset="all"),
        limit=10,
        order_by=(Review.review_date.desc().nullslast(), Review.last_seen_at.desc()),
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
    location_id: str | None = None,
    platform: str | None = None,
    rating: str | None = None,
    status: str | None = None,
    date_preset: str | None = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    per_page = 25
    offset = (page - 1) * per_page
    parsed_location_id = _optional_int(location_id)
    parsed_rating = _optional_int(rating)
    parsed_date_from = _optional_date(date_from)
    parsed_date_to = _optional_date(date_to)

    filters = ReviewFilters(
        location_id=parsed_location_id,
        platform=platform,
        rating=parsed_rating,
        status=status,
        date_preset=date_preset,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )
    order_by = (
        Review.review_date.desc().nullslast(),
        Review.last_seen_at.desc(),
    )
    total = await count_review_listing(db, filters=filters)
    items = await fetch_review_listing(db, filters=filters, limit=per_page, offset=offset, order_by=order_by)
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()

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
                "date_from": parsed_date_from.isoformat() if parsed_date_from else "",
                "date_to": parsed_date_to.isoformat() if parsed_date_to else "",
            },
            "page_query": "&".join(
                f"{key}={value}"
                for key, value in request.query_params.multi_items()
                if key != "page" and value != ""
            ),
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
    location_ids = [location.id for location in locations]
    sources = (
        await db.execute(
            select(ReviewSource)
            .where(ReviewSource.location_id.in_(location_ids))
            .order_by(ReviewSource.location_id, ReviewSource.platform, ReviewSource.id)
        )
    ).scalars().all() if location_ids else []
    sources_by_location: dict[int, list[ReviewSource]] = defaultdict(list)
    for source in sources:
        sources_by_location[source.location_id].append(source)

    google_counts = (
        await db.execute(
            apply_review_filters(
                select(Review.location_id, func.count().label("count"))
                .where(Review.platform == "google")
                .group_by(Review.location_id),
                ReviewFilters(platform="google"),
            )
        )
    ).all()
    yelp_counts = (
        await db.execute(
            apply_review_filters(
                select(Review.location_id, func.count().label("count"))
                .where(Review.platform == "yelp")
                .group_by(Review.location_id),
                ReviewFilters(platform="yelp"),
            )
        )
    ).all()
    google_counts_by_location = {location_id: count for location_id, count in google_counts}
    yelp_counts_by_location = {location_id: count for location_id, count in yelp_counts}

    items = [
        {
            "loc": location,
            "sources": sources_by_location.get(location.id, []),
            "google_count": google_counts_by_location.get(location.id, 0),
            "yelp_count": yelp_counts_by_location.get(location.id, 0),
        }
        for location in locations
    ]
    for item in items:
        enriched_sources = []
        for source in item["sources"]:
            auth_session = await resolve_auth_session_for_source(db, source, location=item["loc"])
            enriched_sources.append(
                {
                    "source": source,
                    "effective_session": auth_session,
                    "using_shared_session": is_shared_session(auth_session, source),
                    "effective_source_url": effective_source_url(source, auth_session),
                }
            )
        item["sources"] = enriched_sources

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
        effective_session = await resolve_auth_session_for_source(db, source, location=location)
        platform_sessions = (
            await db.execute(
                select(AuthSession)
                .where(
                    AuthSession.platform == source.platform,
                    AuthSession.share_scope == "platform",
                )
                .order_by(AuthSession.updated_at.desc())
                .limit(3)
            )
        ).scalars().all()
        items.append(
            {
                "source": source,
                "location": location,
                "sessions": sessions,
                "platform_sessions": platform_sessions,
                "effective_session": effective_session,
                "using_shared_session": is_shared_session(effective_session, source),
                "effective_source_url": effective_source_url(source, effective_session),
            }
        )

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
    resolved_source_url: str = Form(""),
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
    source.resolved_source_url = normalize_source_url_override(source.platform, resolved_source_url) or None
    source.auth_mode = auth_mode
    source.session_status = session_status
    source.settings = settings
    source.is_active = is_active == "on"
    await db.commit()
    return RedirectResponse("/admin/sources", status_code=303)


@router.post("/admin/sources/{source_id}/sessions")
async def admin_add_source_session(
    source_id: int,
    session_reference: str = Form(""),
    session_status: str = Form("active"),
    expires_at: str = Form(""),
    share_scope: str = Form("source"),
    shared_key: str = Form(""),
    source_url_override: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(ReviewSource, source_id)
    if not source:
        return RedirectResponse("/admin/sources", status_code=303)
    if not session_reference.strip():
        return RedirectResponse("/admin/sources", status_code=303)
    location = await db.get(Location, source.location_id)

    parsed_expiry = None
    if expires_at:
        try:
            parsed_expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            parsed_expiry = None

    resolved_scope = normalize_share_scope(share_scope)
    shared_scope_key = build_shared_key(
        platform=source.platform,
        share_scope=resolved_scope,
        source_id=source.id,
        location=location,
        shared_key=shared_key or None,
    )
    target_sources = [source]
    if resolved_scope == "platform":
        target_sources = (
            await db.execute(
                select(ReviewSource)
                .where(
                    ReviewSource.platform == source.platform,
                    ReviewSource.is_active.is_(True),
                )
                .order_by(ReviewSource.location_id, ReviewSource.id)
            )
        ).scalars().all()
    elif resolved_scope == "account":
        account_id = location.google_account_id if location and source.platform == "google" else None
        if account_id:
            target_sources = (
                await db.execute(
                    select(ReviewSource)
                    .join(Location, Location.id == ReviewSource.location_id)
                    .where(
                        ReviewSource.platform == source.platform,
                        ReviewSource.is_active.is_(True),
                        Location.google_account_id == account_id,
                    )
                    .order_by(ReviewSource.location_id, ReviewSource.id)
                )
            ).scalars().all()

    auth_session = AuthSession(
        source_id=source.id,
        platform=source.platform,
        share_scope=resolved_scope,
        shared_key=shared_scope_key,
        session_reference=session_reference,
        source_url_override=normalize_source_url_override(source.platform, source_url_override) or None,
        expires_at=parsed_expiry,
        last_validated_at=datetime.utcnow(),
        status=session_status,
    )
    db.add(auth_session)
    for target_source in target_sources:
        target_source.session_status = session_status
        target_source.last_auth_at = datetime.utcnow()
    if auth_session.source_url_override:
        source.resolved_source_url = auth_session.source_url_override
    await db.commit()
    return RedirectResponse("/admin/sources", status_code=303)
