from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location, ReviewSource


def shared_review_page_key(source: ReviewSource) -> str | None:
    settings = source.settings or {}
    value = settings.get("shared_review_page_key")
    if isinstance(value, str):
        value = value.strip()
    return value or None


def is_shared_review_primary(source: ReviewSource) -> bool:
    settings = source.settings or {}
    return bool(settings.get("shared_review_page_primary"))


def build_google_business_reviews_url(google_location_id: str | None) -> str | None:
    if not google_location_id:
        return None
    return (
        f"https://www.google.com/local/business/{google_location_id}/customers/reviews"
        "?knm=0&ih=lu&origin=https%3A%2F%2Fwww.google.com&hl=en"
    )


def google_source_url_for_location(location: Location | None, source: ReviewSource | None = None) -> str | None:
    settings = source.settings if source and source.settings else {}
    configured_url = settings.get("canonical_google_reviews_url")
    if isinstance(configured_url, str) and configured_url.strip():
        return configured_url.strip()
    if location and location.google_location_id:
        return build_google_business_reviews_url(location.google_location_id)
    return None


async def resolve_canonical_source(
    db: AsyncSession,
    source: ReviewSource,
    *,
    location: Location | None = None,
) -> tuple[ReviewSource, Location | None]:
    group_key = shared_review_page_key(source)
    if not group_key:
        return source, location

    candidates = (
        await db.execute(
            select(ReviewSource)
            .where(
                ReviewSource.platform == source.platform,
                ReviewSource.is_active.is_(True),
            )
            .order_by(ReviewSource.id)
        )
    ).scalars().all()
    grouped = [candidate for candidate in candidates if shared_review_page_key(candidate) == group_key]
    if not grouped:
        return source, location

    canonical_source = next((candidate for candidate in grouped if is_shared_review_primary(candidate)), None)
    if canonical_source is None:
        canonical_source = next(
            (candidate for candidate in grouped if candidate.resolved_source_url),
            None,
        )
    if canonical_source is None:
        canonical_source = grouped[0]

    canonical_location = location
    if canonical_source.id != source.id or location is None or location.id != canonical_source.location_id:
        canonical_location = await db.get(Location, canonical_source.location_id)
    return canonical_source, canonical_location


async def group_sources_for_fetch(
    db: AsyncSession,
    sources: list[ReviewSource],
) -> list[ReviewSource]:
    deduped: list[ReviewSource] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_source_ids: set[int] = set()

    for source in sources:
        group_key = shared_review_page_key(source)
        if not group_key:
            if source.id not in seen_source_ids:
                deduped.append(source)
                seen_source_ids.add(source.id)
            continue

        cache_key = (source.platform, group_key)
        if cache_key in seen_keys:
            continue
        canonical_source, _ = await resolve_canonical_source(db, source)
        if canonical_source.id not in seen_source_ids:
            deduped.append(canonical_source)
            seen_source_ids.add(canonical_source.id)
        seen_keys.add(cache_key)

    return deduped


async def propagate_group_resolved_url(
    db: AsyncSession,
    source: ReviewSource,
    normalized_url: str,
) -> list[int]:
    group_key = shared_review_page_key(source)
    if not group_key:
        source.resolved_source_url = normalized_url
        return [source.id]

    candidates = (
        await db.execute(
            select(ReviewSource)
            .where(
                ReviewSource.platform == source.platform,
                ReviewSource.is_active.is_(True),
            )
            .order_by(ReviewSource.id)
        )
    ).scalars().all()
    updated_ids: list[int] = []
    for candidate in candidates:
        if shared_review_page_key(candidate) != group_key:
            continue
        candidate.resolved_source_url = normalized_url
        if source.platform == "google":
            candidate.source_url = normalized_url
        updated_ids.append(candidate.id)
    return updated_ids
