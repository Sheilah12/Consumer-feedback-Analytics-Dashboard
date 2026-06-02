"""API tests for Vercel-deployed Power Monitor."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

INGEST_BODY = {
    "voltage": 230.0,
    "current_in": 5.0,
    "current_out": 4.85,
    "real_power": 1050.0,
    "energy_kwh_cumulative": 100.0,
}


def _seed(client: TestClient, secret: str = "test-ingest-secret") -> None:
    os_environ = __import__("os").environ
    os_environ["INGEST_SECRET"] = secret
    from app.config import settings

    settings.ingest_secret = secret
    r = client.post(f"/api/blynk/webhook?secret={secret}", json=INGEST_BODY)
    assert r.status_code == 200, r.text


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert body["db"] in ("ok", "error")
    assert "last_ingest_ts" in body
    assert r.headers.get("cache-control") == "no-cache"


def test_webhook_and_latest(client: TestClient):
    _seed(client)
    r = client.get("/api/latest")
    assert r.status_code == 200
    data = r.json()
    assert data["timestamp"].endswith("Z")
    assert data["current_in"] == pytest.approx(5.0, rel=0.01)


def test_readings_paginated(client: TestClient):
    _seed(client)
    r = client.get("/api/readings", params={"limit": 10, "offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert len(body["items"]) >= 1


def test_readings_hourly_cached(client: TestClient):
    _seed(client)
    r = client.get("/api/readings/hourly")
    assert r.status_code == 200
    assert "max-age=30" in r.headers.get("cache-control", "")
    assert isinstance(r.json(), list)


def test_readings_daily_cached(client: TestClient):
    _seed(client)
    r = client.get("/api/readings/daily")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_alerts_paginated(client: TestClient):
    r = client.get("/api/alerts", params={"limit": 10, "acknowledged": False})
    assert r.status_code == 200
    assert "items" in r.json()


def test_config_get(client: TestClient):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert "token_set" in data
    assert data["currency"] == "KES"


def test_stats_summary(client: TestClient):
    _seed(client)
    r = client.get("/api/stats/summary")
    assert r.status_code == 200
    for key in ("today_kwh", "month_kwh", "month_cost_kes", "alert_count_today", "uptime_pct"):
        assert key in r.json()


def test_budget_estimate(client: TestClient):
    _seed(client)
    r = client.get("/api/budget/estimate", params={"hours": 24, "cap_kwh": 100})
    assert r.status_code == 200
    assert "estimated_cost_kes" in r.json()


def test_webhook_rejects_bad_secret(client: TestClient):
    r = client.post("/api/blynk/webhook?secret=wrong", json=INGEST_BODY)
    assert r.status_code == 401


def test_cron_prune_unauthorized(client: TestClient):
    r = client.get("/api/cron/prune")
    assert r.status_code in (401, 503)
