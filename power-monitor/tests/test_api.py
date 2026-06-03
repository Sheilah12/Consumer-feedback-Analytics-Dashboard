"""API tests for Vercel-deployed Power Monitor."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

INGEST_BODY = {
    "live_current": 5.0,
    "neutral_current": 4.85,
    "differential": 0.15,
    "voltage": 230.0,
    "real_power": 1050.0,
    "energy_kwh_cumulative": 100.0,
    "system_status": "alert",
    "ts": "2026-05-30T12:00:00.000Z",
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
    assert data["ts"].endswith("Z")
    assert data["timestamp"].endswith("Z")
    assert data["live_current"] == pytest.approx(5.0, rel=0.01)
    assert data["neutral_current"] == pytest.approx(4.85, rel=0.01)
    assert data["system_status"] == "alert"
    assert data["tier"] == "investigation"
    assert data["hardware_alert"] is False
    assert data["current_in"] == pytest.approx(5.0, rel=0.01)


def test_webhook_isolated_stored(client: TestClient):
    os_environ = __import__("os").environ
    secret = "test-ingest-secret"
    os_environ["INGEST_SECRET"] = secret
    from app.config import settings

    settings.ingest_secret = secret
    body = {
        **INGEST_BODY,
        "system_status": "isolated",
        "differential": 0.35,
        "energy_kwh_cumulative": 101.0,
    }
    r = client.post(f"/api/blynk/webhook?secret={secret}", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["system_status"] == "isolated"
    assert data["tier"] == "isolation"
    assert data["hardware_alert"] is True

    latest = client.get("/api/latest").json()
    assert latest["system_status"] == "isolated"
    assert latest["hardware_alert"] is True

    alerts = client.get("/api/alerts", params={"limit": 5}).json()
    assert alerts["items"][0]["tier"] == "isolation"


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


def test_budget_cap_endpoint(client: TestClient):
    _seed(client)
    r = client.get("/api/budget/cap")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "month_to_date_kwh",
        "month_to_date_cost",
        "monthly_budget_kes",
        "pct_used",
        "projected_month_cost",
        "on_track",
    ):
        assert key in data


def test_config_monthly_budget(client: TestClient):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert "monthly_budget_kes" in r.json()


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
