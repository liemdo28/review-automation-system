from __future__ import annotations

import pytest

from app.routes import api as api_routes
from tests.conftest import FakeAsyncSession


@pytest.mark.asyncio
async def test_stats_returns_expected_summary(monkeypatch):
    async def fake_count_reviews(_db, platform=None, negative_only=False):
        if negative_only:
            return 2
        if platform == "google":
            return 3
        if platform == "yelp":
            return 1
        return 4

    monkeypatch.setattr(api_routes, "count_reviews", fake_count_reviews)
    db = FakeAsyncSession([2, 1, 5, 0, 1, 0, 3, 2])

    response = await api_routes.stats(db)

    assert response["total_unreplied_reviews"] == 4
    assert response["google_unreplied_reviews"] == 3
    assert response["yelp_unreplied_reviews"] == 1
    assert response["negative_reviews_needing_attention"] == 2
    assert response["blocked_auth_reviews"] == 2
