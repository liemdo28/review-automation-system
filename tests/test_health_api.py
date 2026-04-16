from __future__ import annotations

import pytest

from app.routes import api as api_routes
from tests.conftest import FakeAsyncSession


@pytest.mark.asyncio
async def test_health_reports_ok_when_db_query_succeeds():
    response = await api_routes.health(FakeAsyncSession([1]))
    assert response["status"] == "ok"
    assert response["database"] == "connected"


@pytest.mark.asyncio
async def test_health_reports_error_when_db_query_fails():
    class BrokenSession:
        async def execute(self, _query):
            raise RuntimeError("db down")

    response = await api_routes.health(BrokenSession())
    assert response["status"] == "error"
    assert "db down" in response["database"]
