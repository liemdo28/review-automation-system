from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import AuthSession, Location, ReviewSource


def normalize_share_scope(share_scope: str | None) -> str:
    scope = (share_scope or "source").strip().lower()
    if scope not in {"source", "platform", "account"}:
        return "source"
    return scope


def build_shared_key(
    *,
    platform: str,
    share_scope: str,
    source_id: int | None = None,
    location: Location | None = None,
    shared_key: str | None = None,
) -> str | None:
    scope = normalize_share_scope(share_scope)
    if scope == "source":
        return f"source:{source_id}" if source_id is not None else None
    if shared_key:
        return shared_key.strip() or None
    if scope == "platform":
        return f"platform:{platform}"
    if scope == "account":
        account_key = None
        if platform == "google":
            account_key = location.google_account_id if location else None
        return f"account:{platform}:{account_key}" if account_key else None
    return None


def force_google_review_language(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["hl"] = "en"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_source_url_override(platform: str, source_url_override: str | None) -> str | None:
    if not source_url_override:
        return None

    candidate = source_url_override.strip()
    lowered = candidate.lower()
    platform = (platform or "").lower()

    if platform == "google" and "/local/business/" in lowered and "/customers/reviews" in lowered:
        return force_google_review_language(candidate)
    if platform == "yelp" and "yelp.com/biz/" in lowered:
        return candidate
    return None


async def resolve_auth_session_for_source(
    db: AsyncSession,
    source: ReviewSource,
    *,
    location: Location | None = None,
) -> AuthSession | None:
    now = datetime.utcnow()
    active_filter = and_(
        AuthSession.platform == source.platform,
        AuthSession.status == "active",
        or_(AuthSession.expires_at.is_(None), AuthSession.expires_at > now),
    )

    source_session = (
        await db.execute(
            select(AuthSession)
            .where(
                and_(
                    active_filter,
                    AuthSession.source_id == source.id,
                    AuthSession.share_scope == "source",
                )
            )
            .order_by(AuthSession.last_validated_at.desc().nullslast(), AuthSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if source_session:
        return source_session

    platform_key = build_shared_key(platform=source.platform, share_scope="platform")
    platform_session = (
        await db.execute(
            select(AuthSession)
            .where(
                and_(
                    active_filter,
                    AuthSession.share_scope == "platform",
                    or_(AuthSession.shared_key == platform_key, AuthSession.shared_key.is_(None)),
                )
            )
            .order_by(AuthSession.last_validated_at.desc().nullslast(), AuthSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if platform_session:
        return platform_session

    account_key = build_shared_key(
        platform=source.platform,
        share_scope="account",
        location=location,
    )
    if account_key:
        return (
            await db.execute(
                select(AuthSession)
                .where(
                    and_(
                        active_filter,
                        AuthSession.share_scope == "account",
                        AuthSession.shared_key == account_key,
                    )
                )
                .order_by(AuthSession.last_validated_at.desc().nullslast(), AuthSession.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return None


def resolve_auth_session_for_source_sync(
    db: Session,
    source: ReviewSource,
    *,
    location: Location | None = None,
) -> AuthSession | None:
    now = datetime.utcnow()
    active_filter = and_(
        AuthSession.platform == source.platform,
        AuthSession.status == "active",
        or_(AuthSession.expires_at.is_(None), AuthSession.expires_at > now),
    )

    source_session = (
        db.execute(
            select(AuthSession)
            .where(
                and_(
                    active_filter,
                    AuthSession.source_id == source.id,
                    AuthSession.share_scope == "source",
                )
            )
            .order_by(AuthSession.last_validated_at.desc().nullslast(), AuthSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if source_session:
        return source_session

    platform_key = build_shared_key(platform=source.platform, share_scope="platform")
    platform_session = (
        db.execute(
            select(AuthSession)
            .where(
                and_(
                    active_filter,
                    AuthSession.share_scope == "platform",
                    or_(AuthSession.shared_key == platform_key, AuthSession.shared_key.is_(None)),
                )
            )
            .order_by(AuthSession.last_validated_at.desc().nullslast(), AuthSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if platform_session:
        return platform_session

    account_key = build_shared_key(
        platform=source.platform,
        share_scope="account",
        location=location,
    )
    if account_key:
        return (
            db.execute(
                select(AuthSession)
                .where(
                    and_(
                        active_filter,
                        AuthSession.share_scope == "account",
                        AuthSession.shared_key == account_key,
                    )
                )
                .order_by(AuthSession.last_validated_at.desc().nullslast(), AuthSession.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return None


def effective_source_url(source: ReviewSource, auth_session: AuthSession | None = None) -> str | None:
    if getattr(source, "resolved_source_url", None):
        return source.resolved_source_url

    if (
        auth_session
        and auth_session.share_scope == "source"
        and auth_session.source_id == source.id
        and auth_session.source_url_override
    ):
        return auth_session.source_url_override

    return source.source_url


def is_shared_session(auth_session: AuthSession | None, source: ReviewSource) -> bool:
    if not auth_session:
        return False
    return auth_session.share_scope != "source" or auth_session.source_id != source.id
