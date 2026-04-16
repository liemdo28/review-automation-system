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

from app.config import settings
from app.database import get_db
from app.models import AuthSession, Job, Location, Reply, ReplySuggestion, Review, ReviewSource
from app.services.auto_reply_refresh import reevaluate_reviews_for_sources
from app.services.auto_reply_policy import load_effective_auto_reply_config, load_global_auto_reply_config
from app.services.review_ops import ReviewFilters, apply_review_filters, count_reviews, derive_review_status
from app.services.store_theme import store_theme_for_location, store_theme_style
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
SOURCE_BLOCKED_STATUSES = {"reauth_required", "failed", "expired", "blocked", "missing"}


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


def _parse_rating_values(raw_values: list[str] | None, fallback: str | None = None) -> list[int] | None:
    values = list(raw_values or [])
    if fallback is not None:
        values.append(fallback)

    ratings: list[int] = []
    seen: set[int] = set()
    for raw in values:
        if raw is None:
            continue
        for piece in str(raw).split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                rating = int(piece)
            except ValueError:
                continue
            if rating < 1 or rating > 5 or rating in seen:
                continue
            seen.add(rating)
            ratings.append(rating)
    return ratings or None


async def _build_shell_counts(db: AsyncSession) -> dict[str, int]:
    queue_count = await count_reviews(db)
    auto_eligible = (
        await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "auto_post_eligible"))
    ).scalar() or 0
    escalated = (
        await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "escalated"))
    ).scalar() or 0
    auth_blocked = (
        await db.execute(
            select(func.count()).select_from(ReviewSource).where(ReviewSource.session_status.in_(SOURCE_BLOCKED_STATUSES))
        )
    ).scalar() or 0
    manual_review = (
        await db.execute(
            select(func.count()).select_from(Review).where(Review.workflow_status == "manual_review_required")
        )
    ).scalar() or 0
    # --- queue blocking breakdown ---
    needs_login = (
        await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "blocked_auth"))
    ).scalar() or 0
    needs_draft = (
        await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "unreplied"))
    ).scalar() or 0
    escalated_count = escalated or 0
    policy_blocked = (
        await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "manual_review_required"))
    ).scalar() or 0
    return {
        "queue": queue_count,
        "auto_eligible": auto_eligible,
        "escalated": escalated,
        "auth_blocked": auth_blocked,
        "manual_review": manual_review,
        # New: queue blocking breakdown — used by reviews.html onboarding banner
        "queue_blocking_summary": {
            "login_required": needs_login,
            "draft_missing": needs_draft,
            "escalated": escalated_count,
            "policy_blocked": policy_blocked,
        },
    }


async def _build_shell_context(
    db: AsyncSession,
    *,
    page_key: str,
    scope_label: str = "All stores",
    ai_context: dict | None = None,
) -> dict:
    shell_counts = await _build_shell_counts(db)
    blocked = shell_counts["auth_blocked"]
    health_label = "Needs login" if blocked else "Healthy"
    health_tone = "failed" if blocked else "posted"
    default_ai_context = {
        "title": "AI workspace context",
        "summary": "Use the left rail to move between queue, automation, audit, and source recovery without losing decision context.",
        "sections": [
            {"label": "Queue ready", "value": f"{shell_counts['queue']} open reviews"},
            {"label": "Auto eligible", "value": f"{shell_counts['auto_eligible']} reviews"},
            {"label": "Escalated", "value": f"{shell_counts['escalated']} reviews"},
            {"label": "Auth blocked", "value": f"{shell_counts['auth_blocked']} sources"},
        ],
        "actions": [
            {"label": "Open Queue", "href": "/reviews"},
            {"label": "Open Auto Reply", "href": "/auto-reply"},
            {"label": "Open Audit", "href": "/audit"},
        ],
    }
    context = ai_context or default_ai_context
    return {
        "shell_page_key": page_key,
        "shell_counts": shell_counts,
        "shell_scope_label": scope_label,
        "shell_health_label": health_label,
        "shell_health_tone": health_tone,
        "shell_command_suggestions": [
            {"label": "1-star last 7 days", "command": "Show me 1-star reviews from last 7 days"},
            {"label": "Auto reply ready", "command": "Find reviews safe for auto reply"},
            {"label": "GM report", "command": "Generate GM report"},
            {"label": "Auth issues", "command": "Show stores with auth issues"},
        ],
        "ai_context_title": context.get("title"),
        "ai_context_summary": context.get("summary"),
        "ai_context_sections": context.get("sections", []),
        "ai_context_actions": context.get("actions", []),
    }


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    summary = {
        "total_unreplied_reviews": await count_reviews(db),
        "google_unreplied_reviews": await count_reviews(db, platform="google"),
        "yelp_unreplied_reviews": await count_reviews(db, platform="yelp"),
        "negative_reviews_needing_attention": await count_reviews(db, negative_only=True),
        "negative_reviews_today": (
            await db.execute(
                select(func.count()).select_from(Review).where(
                    Review.rating <= 3,
                    Review.review_date >= today_start,
                )
            )
        ).scalar()
        or 0,
        "escalated_reviews": (
            await db.execute(select(func.count()).select_from(Review).where(Review.workflow_status == "escalated"))
        ).scalar()
        or 0,
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

    shell_context = await _build_shell_context(
        db,
        page_key="overview",
        ai_context={
            "title": "AI Overview",
            "summary": (
                f"{summary['total_unreplied_reviews']} open reviews, "
                f"{summary['negative_reviews_needing_attention']} negative items, and "
                f"{summary['auth_expired_jobs']} sources needing login."
            ),
            "sections": [
                {"label": "Auto eligible", "value": f"{summary.get('auto_post_eligible_today', 0)} ready today"},
                {"label": "Negative today", "value": f"{summary['negative_reviews_today']} flagged"},
                {"label": "Escalated", "value": f"{summary['escalated_reviews']} reviews"},
                {"label": "Failed jobs", "value": f"{summary['failed_jobs']} events"},
            ],
            "actions": [
                {"label": "Run Auto Reply", "href": "/auto-reply"},
                {"label": "Open Audit", "href": "/audit"},
                {"label": "Recover Sources", "href": "/locations"},
            ],
        },
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
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
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
    focus_id: int | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    per_page = 25
    offset = (page - 1) * per_page
    parsed_location_id = _optional_int(location_id)
    parsed_ratings = _parse_rating_values(request.query_params.getlist("ratings"), rating)
    parsed_rating = parsed_ratings[0] if parsed_ratings and len(parsed_ratings) == 1 else None
    parsed_date_from = _optional_date(date_from)
    parsed_date_to = _optional_date(date_to)

    filters = ReviewFilters(
        location_id=parsed_location_id,
        platform=platform,
        rating=parsed_rating,
        ratings=parsed_ratings,
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
    focus_review = await db.get(Review, focus_id) if focus_id else None
    focus_reply = (
        await db.execute(select(Reply).where(Reply.review_id == focus_review.id))
    ).scalar_one_or_none() if focus_review else None
    focus_source = await db.get(ReviewSource, focus_review.source_id) if focus_review and focus_review.source_id else None
    focus_location = await db.get(Location, focus_review.location_id) if focus_review else None
    shell_context = await _build_shell_context(
        db,
        page_key="queue",
        ai_context={
            "title": "Queue AI assistant",
            "summary": (
                f"{total} reviews match the current filters. "
                "Use the sticky presets and bulk actions to move through safe approvals first."
            ),
            "sections": [
                {"label": "Current filter", "value": status.replace("_", " ") if status else "Needs attention"},
                {"label": "Star filter", "value": ", ".join(str(r) for r in parsed_ratings) if parsed_ratings else "All ratings"},
                {"label": "Date scope", "value": date_preset or "all"},
                {"label": "Focused review", "value": focus_review.reviewer_name if focus_review else "Select a review card"},
            ],
            "actions": [
                {"label": "Auto Reply workspace", "href": "/auto-reply"},
                {"label": "Negative Audit", "href": "/audit"},
            ],
        },
    )

    global_config = await load_global_auto_reply_config(db)
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
                "ratings": parsed_ratings or [],
                "status": status,
                "date_preset": date_preset,
                "date_from": parsed_date_from.isoformat() if parsed_date_from else "",
                "date_to": parsed_date_to.isoformat() if parsed_date_to else "",
            },
            "page_query": "&".join(
                f"{key}={value}"
                for key, value in request.query_params.multi_items()
                if key not in {"page", "focus_id"} and value != ""
            ),
            "focus_review": focus_review,
            "focus_reply": focus_reply,
            "focus_source": focus_source,
            "focus_location": focus_location,
            "global_auto_reply_config": global_config,
            "dry_run": settings.dry_run,
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
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
    auto_reply_config = await load_effective_auto_reply_config(db, location=location)
    jobs = (
        await db.execute(select(Job).where(Job.review_id == review.id).order_by(Job.queued_at.desc()))
    ).scalars().all()

    shell_context = await _build_shell_context(
        db,
        page_key="queue",
        scope_label=location.name if location else "All stores",
        ai_context={
            "title": "Review detail context",
            "summary": review.auto_reply_decision_reason or "Inspect the full draft, risk summary, and source state before acting.",
            "sections": [
                {"label": "Reviewer", "value": review.reviewer_name or "Anonymous"},
                {"label": "Rating", "value": f"{review.rating}/5"},
                {"label": "Workflow", "value": review.workflow_status or review_status},
                {"label": "Source", "value": source.source_label if source else "Unknown source"},
            ],
            "actions": [
                {"label": "Back to Queue", "href": "/reviews"},
                {"label": "Open Source", "href": (source.resolved_source_url or source.source_url) if source else "/reviews"},
            ],
        },
    )

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
            "auto_reply_config": auto_reply_config,
            "dry_run": settings.dry_run,
            "jobs": jobs,
            "review_status": derive_review_status(review, reply, jobs[0] if jobs else None),
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
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

    shell_context = await _build_shell_context(
        db,
        page_key="sources",
        ai_context={
            "title": "Source recovery",
            "summary": "Use shared login when one operator account powers multiple stores. Resolve blocked sessions before queue automation.",
            "sections": [
                {"label": "Stores", "value": str(len(items))},
                {"label": "Google open", "value": str(sum(item["google_count"] for item in items))},
                {"label": "Yelp open", "value": str(sum(item["yelp_count"] for item in items))},
                {"label": "Auth blocked", "value": str(sum(1 for item in items for src in item["sources"] if src["source"].session_status in SOURCE_BLOCKED_STATUSES))},
            ],
            "actions": [
                {"label": "Open Admin", "href": "/admin/sources"},
                {"label": "Sync Queue", "href": "/reviews"},
            ],
        },
    )

    return templates.TemplateResponse(
        request=request,
        name="locations.html",
        context={
            "request": request,
            "locations": items,
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
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

    shell_context = await _build_shell_context(
        db,
        page_key="admin",
        ai_context={
            "title": "Source admin",
            "summary": "Attach session files, override resolved URLs, and keep shared login behavior explicit before automation runs.",
            "sections": [
                {"label": "Sources", "value": str(len(items))},
                {"label": "Shared sessions", "value": str(sum(1 for item in items if item["using_shared_session"]))},
                {"label": "Blocked auth", "value": str(sum(1 for item in items if item["source"].session_status in SOURCE_BLOCKED_STATUSES))},
                {"label": "Platforms", "value": ", ".join(sorted({item["source"].platform.title() for item in items})) or "-"},
            ],
            "actions": [
                {"label": "Locations", "href": "/locations"},
                {"label": "Auto Reply config", "href": "/admin/auto-reply"},
            ],
        },
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_sources.html",
        context={
            "request": request,
            "items": items,
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
        },
    )


@router.get("/admin/auto-reply")
async def admin_auto_reply_page(request: Request, db: AsyncSession = Depends(get_db)):
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    global_config = await load_global_auto_reply_config(db)
    shell_context = await _build_shell_context(
        db,
        page_key="admin",
        ai_context={
            "title": "Policy control",
            "summary": "Tune eligibility, quiet hours, blocked keywords, and escalation routing before turning on live automation.",
            "sections": [
                {"label": "Auto reply", "value": "Enabled" if global_config.get("auto_reply_enabled") else "Paused"},
                {"label": "Google auto-post", "value": "Enabled" if global_config.get("auto_post_phase_enabled") else "Disabled"},
                {"label": "Min rating", "value": str(global_config.get("auto_reply_min_rating"))},
                {"label": "Daily cap", "value": str(global_config.get("auto_reply_daily_limit"))},
            ],
            "actions": [
                {"label": "Auto Reply workspace", "href": "/auto-reply"},
                {"label": "Audit workspace", "href": "/audit"},
            ],
        },
    )
    return templates.TemplateResponse(
        request=request,
        name="admin_auto_reply.html",
        context={
            "request": request,
            "locations": locations,
            "global_config": global_config,
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
        },
    )


@router.get("/auto-reply")
async def auto_reply_workspace(request: Request, db: AsyncSession = Depends(get_db)):
    eligible_items = await fetch_review_listing(
        db,
        filters=ReviewFilters(status="auto_post_eligible", date_preset="30d"),
        limit=20,
        order_by=(Review.review_date.desc().nullslast(), Review.last_seen_at.desc()),
    )
    blocked_items = await fetch_review_listing(
        db,
        filters=ReviewFilters(status="blocked_auth", date_preset="30d"),
        limit=10,
        order_by=(Review.review_date.desc().nullslast(), Review.last_seen_at.desc()),
    )
    failed_items = await fetch_review_listing(
        db,
        filters=ReviewFilters(status="auto_post_failed", date_preset="30d"),
        limit=10,
        order_by=(Review.last_seen_at.desc(),),
    )
    global_config = await load_global_auto_reply_config(db)
    sources = (await db.execute(select(ReviewSource).order_by(ReviewSource.location_id, ReviewSource.platform))).scalars().all()
    healthy_sources = sum(1 for source in sources if source.session_status == "active")
    paused_sources = sum(1 for source in sources if source.session_status in SOURCE_BLOCKED_STATUSES)
    shell_context = await _build_shell_context(
        db,
        page_key="auto_reply",
        ai_context={
            "title": "Auto Reply control",
            "summary": "Run safe reviews first, watch blocked dependencies, and keep live posting paused until sessions and policy both pass.",
            "sections": [
                {"label": "Eligible queue", "value": str(len(eligible_items))},
                {"label": "Blocked auth", "value": str(len(blocked_items))},
                {"label": "Failures", "value": str(len(failed_items))},
                {"label": "Healthy sources", "value": f"{healthy_sources}/{len(sources) or 1}"},
            ],
            "actions": [
                {"label": "Open Queue", "href": "/reviews?status=auto_post_eligible"},
                {"label": "Open Policy", "href": "/admin/auto-reply"},
            ],
        },
    )
    return templates.TemplateResponse(
        request=request,
        name="auto_reply.html",
        context={
            "request": request,
            "eligible_items": eligible_items,
            "blocked_items": blocked_items,
            "failed_items": failed_items,
            "global_config": global_config,
            "dry_run": settings.dry_run,
            "healthy_sources": healthy_sources,
            "paused_sources": paused_sources,
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
        },
    )


@router.get("/audit")
async def audit_workspace(request: Request, db: AsyncSession = Depends(get_db)):
    audit_items = await fetch_review_listing(
        db,
        filters=ReviewFilters(ratings=[1, 2, 3], date_preset="30d"),
        limit=30,
        order_by=(Review.review_date.desc().nullslast(), Review.last_seen_at.desc()),
    )
    by_store = (
        await db.execute(
            select(Location.name, func.count(Review.id))
            .join(Review, Review.location_id == Location.id)
            .where(Review.rating <= 3)
            .group_by(Location.name)
            .order_by(func.count(Review.id).desc(), Location.name)
        )
    ).all()
    by_issue = (
        await db.execute(
            select(Review.issue_category, func.count(Review.id))
            .where(Review.rating <= 3)
            .group_by(Review.issue_category)
            .order_by(func.count(Review.id).desc())
        )
    ).all()
    by_severity = (
        await db.execute(
            select(Review.severity_level, func.count(Review.id))
            .where(Review.rating <= 3)
            .group_by(Review.severity_level)
            .order_by(func.count(Review.id).desc())
        )
    ).all()
    report = await load_global_auto_reply_config(db)
    shell_context = await _build_shell_context(
        db,
        page_key="audit",
        ai_context={
            "title": "Negative review audit",
            "summary": "Everything at 3 stars and below stays visible here for issue analysis, escalation, and GM reporting.",
            "sections": [
                {"label": "Audit queue", "value": str(len(audit_items))},
                {"label": "Top store", "value": by_store[0][0] if by_store else "-"},
                {"label": "Top issue", "value": (by_issue[0][0] or "-").replace("_", " ") if by_issue else "-"},
                {"label": "Highest severity", "value": by_severity[0][0] if by_severity else "-"},
            ],
            "actions": [
                {"label": "Generate GM report", "href": "/reports"},
                {"label": "Open Queue", "href": "/reviews?ratings=1&ratings=2&ratings=3"},
            ],
        },
    )
    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={
            "request": request,
            "audit_items": audit_items,
            "by_store": by_store,
            "by_issue": by_issue,
            "by_severity": by_severity,
            "global_config": report,
            "store_theme": store_theme_for_location,
            "store_theme_style": store_theme_style,
            **shell_context,
        },
    )


@router.get("/reports")
async def reports_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.services.gm_report import build_daily_negative_review_report

    report = await build_daily_negative_review_report(db)
    shell_context = await _build_shell_context(
        db,
        page_key="reports",
        ai_context={
            "title": "Reports workspace",
            "summary": "Daily GM reporting and automation outcomes stay here so operators can summarize what happened without leaving the tool.",
            "sections": [
                {"label": "Negative reviews", "value": str(report.total_reviews)},
                {"label": "Top serious issues", "value": str(len(report.serious_issues))},
                {"label": "Stores in report", "value": str(len(report.by_store))},
                {"label": "Suggested actions", "value": str(len(report.suggested_actions))},
            ],
            "actions": [
                {"label": "Open Audit", "href": "/audit"},
                {"label": "Send GM report", "href": "/reports"},
            ],
        },
    )
    return templates.TemplateResponse(
        request=request,
        name="reports.html",
        context={
            "request": request,
            "report": report,
            **shell_context,
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
    previous_session_status = source.session_status
    previous_effective_url = source.resolved_source_url or source.source_url

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
    if source.session_status == "active" and (
        previous_session_status != "active"
        or (source.resolved_source_url or source.source_url) != previous_effective_url
    ):
        await reevaluate_reviews_for_sources(db, source_ids=[source.id])
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
    if session_status == "active":
        refresh_ids = [target_source.id for target_source in target_sources]
        await reevaluate_reviews_for_sources(db, source_ids=refresh_ids)
    await db.commit()
    return RedirectResponse("/admin/sources", status_code=303)
