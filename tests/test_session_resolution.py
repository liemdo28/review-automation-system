from __future__ import annotations

from types import SimpleNamespace

from app.services.session_resolution import (
    build_shared_key,
    effective_source_url,
    normalize_share_scope,
    normalize_source_url_override,
)


def test_normalize_share_scope_falls_back_to_source():
    assert normalize_share_scope("weird") == "source"


def test_build_platform_shared_key():
    assert build_shared_key(platform="google", share_scope="platform") == "platform:google"


def test_google_source_override_keeps_review_url_and_forces_english():
    url = "https://www.google.com/local/business/123/customers/reviews?hl=vi"
    normalized = normalize_source_url_override("google", url)
    assert normalized is not None
    assert "hl=en" in normalized


def test_effective_source_url_prefers_resolved_source():
    source = SimpleNamespace(
        source_url="https://example.com/original",
        resolved_source_url="https://example.com/resolved",
        id=1,
    )
    assert effective_source_url(source, None) == "https://example.com/resolved"
