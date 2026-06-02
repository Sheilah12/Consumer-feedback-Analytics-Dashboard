"""Shared pytest fixtures — requires DATABASE_URL for integration tests."""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("INGEST_SECRET", "test-ingest-secret")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

from fastapi.testclient import TestClient  # noqa: E402


def pytest_collection_modifyitems(config, items):
    if DATABASE_URL:
        return
    reason = "DATABASE_URL not set — point at Neon or local Postgres"
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if item.get_closest_marker("unit"):
            continue
        item.add_marker(skip)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module", autouse=True)
def prepare_database(event_loop):
    if not DATABASE_URL:
        yield
        return

    from app.db import connect, ensure_schema

    async def _reset():
        await ensure_schema()
        async with connect() as conn:
            await conn.execute("TRUNCATE readings, alerts RESTART IDENTITY")

    event_loop.run_until_complete(_reset())
    yield


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.config import settings
    from app.routes import app

    settings.ingest_secret = os.environ.get("INGEST_SECRET", "test-ingest-secret")
    if DATABASE_URL:
        settings.database_url = DATABASE_URL

    with TestClient(app) as test_client:
        yield test_client
