from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Request

from app.routes import dashboard as dashboard_routes


@pytest.mark.asyncio
async def test_reviews_page_handles_empty_state(monkeypatch):
    async def fake_count_review_listing(*_args, **_kwargs):
        return 0

    async def fake_fetch_review_listing(*_args, **_kwargs):
        return []

    async def fake_shell_context(*_args, **_kwargs):
        return {
            "shell_page_key": "queue",
            "shell_counts": {"queue": 0, "auto_eligible": 0, "escalated": 0, "auth_blocked": 0, "manual_review": 0},
            "shell_scope_label": "All stores",
            "shell_health_label": "Healthy",
            "shell_health_tone": "posted",
            "shell_command_suggestions": [],
            "ai_context_title": "Queue",
            "ai_context_summary": "Empty",
            "ai_context_sections": [],
            "ai_context_actions": [],
        }

    async def fake_load_global_auto_reply_config(_db):
        return {"auto_reply_enabled": True}

    class FakeDB:
        async def execute(self, _query):
            class _Result:
                def scalars(self):
                    return self

                def all(self):
                    return []

            return _Result()

        async def get(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(dashboard_routes, "count_review_listing", fake_count_review_listing)
    monkeypatch.setattr(dashboard_routes, "fetch_review_listing", fake_fetch_review_listing)
    monkeypatch.setattr(dashboard_routes, "_build_shell_context", fake_shell_context)
    monkeypatch.setattr(dashboard_routes, "load_global_auto_reply_config", fake_load_global_auto_reply_config)

    scope = {"type": "http", "method": "GET", "path": "/reviews", "query_string": b""}
    request = Request(scope)
    response = await dashboard_routes.reviews_page(request=request, db=FakeDB())

    assert response.status_code == 200
    assert response.context["total"] == 0
    assert response.context["items"] == []


def test_parse_rating_values_supports_multi_select():
    assert dashboard_routes._parse_rating_values(["5", "4"], None) == [5, 4]
