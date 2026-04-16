from __future__ import annotations

from types import SimpleNamespace

import pytest


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self._value, list):
            return self._value
        return []


class FakeAsyncSession:
    def __init__(self, values: list):
        self._values = list(values)

    async def execute(self, _query):
        if self._values:
            return FakeScalarResult(self._values.pop(0))
        return FakeScalarResult(None)

    async def get(self, _model, _key):
        return None


@pytest.fixture
def fake_location():
    return SimpleNamespace(
        id=1,
        name="Bakudan Ramen",
        auto_reply_settings={},
        google_account_id="acct-1",
    )
