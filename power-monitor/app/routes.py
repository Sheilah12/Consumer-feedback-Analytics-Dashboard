"""FastAPI routes — stateless REST API for Vercel serverless."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app import db, ingest
from app.api_serializers import alert_to_api, reading_to_api
from app.config import settings
from app.models import (
    AlertAck,
    BudgetEstimate,
    ConfigResponse,
    ConfigUpdate,
    HealthResponse,
    PaginatedAlerts,
    PaginatedReadings,
    SettingsResponse,
    SettingsUpdate,
    StatsSummary,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Power Monitor",
    description="Lightweight power theft detection and energy monitoring",
    version="2.0.0",
    debug=settings.debug,
)


def _no_cache(content) -> JSONResponse:
    return JSONResponse(content, headers={"Cache-Control": "no-cache"})


def _cached(content, max_age: int = 30) -> JSONResponse:
    return JSONResponse(
        content,
        headers={"Cache-Control": f"max-age={max_age}, public"},
    )


def _parse_iso8601(value: Optional[str], name: str) -> Optional[str]:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {name}: {value}") from exc


def _verify_admin(request: Request) -> None:
    if not settings.admin_token:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {settings.admin_token}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _verify_cron(request: Request) -> None:
    secret = settings.cron_secret
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _uptime_pct() -> float:
    last = await db.get_last_ingest_ts()
    if last is None:
        return 0.0
    age = (datetime.now(timezone.utc) - last).total_seconds()
    if age <= 120:
        return 100.0
    if age <= 600:
        return 85.0
    return 50.0


async def _blynk_health() -> str:
    token = settings.blynk_token.strip()
    if not token:
        return "not_configured"
    last = await db.get_last_ingest_ts()
    if last is None:
        return "degraded"
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return "ok" if age <= 120 else "degraded"


def _token_set() -> bool:
    token = settings.blynk_token.strip()
    stored = False
    return bool(token)


async def _config_response() -> ConfigResponse:
    token = settings.blynk_token.strip()
    stored_token = await db.get_setting("blynk_token", "")
    return ConfigResponse(
        alert_threshold_ma=await db.get_alert_threshold_ma(),
        tariff_kwh_cost=round(await db.get_tariff(), 2),
        currency=settings.currency,
        token_set=bool(token or stored_token),
    )


@app.get("/api/health", response_model=HealthResponse)
async def health() -> JSONResponse:
    db_ok = await db.check_db_ok()
    last_ts = await db.get_last_ingest_ts()
    db_size = await db.get_db_size_bytes() if db_ok else None
    body = HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "error",
        blynk=await _blynk_health(),
        last_ingest_ts=last_ts.isoformat().replace("+00:00", "Z") if last_ts else None,
        db_size_bytes=db_size,
        demo_mode=False,
    )
    return _no_cache(body.model_dump())


@app.get("/api/latest")
async def api_latest() -> JSONResponse:
    reading = await db.get_latest_reading()
    if not reading:
        raise HTTPException(status_code=404, detail="No readings yet")
    return _no_cache(reading_to_api(reading))


@app.get("/api/readings", response_model=PaginatedReadings)
async def api_readings(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
) -> JSONResponse:
    from_iso = _parse_iso8601(from_, "from")
    to_iso = _parse_iso8601(to, "to")
    total = await db.count_readings(from_iso=from_iso, to_iso=to_iso)
    rows = await db.get_readings_paginated(
        limit=limit, offset=offset, from_iso=from_iso, to_iso=to_iso
    )
    payload = PaginatedReadings(
        items=[reading_to_api(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
    return _no_cache(payload.model_dump())


@app.get("/api/readings/hourly")
async def api_readings_hourly(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
) -> JSONResponse:
    from_iso = _parse_iso8601(from_, "from") if from_ else None
    to_iso = _parse_iso8601(to, "to") if to else None
    buckets = await db.get_readings_hourly(from_iso=from_iso, to_iso=to_iso)
    return _cached([b.model_dump() for b in buckets], max_age=30)


@app.get("/api/readings/daily")
async def api_readings_daily(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
) -> JSONResponse:
    from_iso = _parse_iso8601(from_, "from") if from_ else None
    to_iso = _parse_iso8601(to, "to") if to else None
    buckets = await db.get_readings_daily(from_iso=from_iso, to_iso=to_iso)
    return _cached([b.model_dump() for b in buckets], max_age=30)


@app.get("/api/alerts", response_model=PaginatedAlerts)
async def api_alerts(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    acknowledged: Optional[bool] = Query(None),
) -> JSONResponse:
    total = await db.count_alerts(acknowledged=acknowledged)
    rows = await db.get_alerts_paginated(
        limit=limit, offset=offset, acknowledged=acknowledged
    )
    payload = PaginatedAlerts(
        items=[alert_to_api(a) for a in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
    return _no_cache(payload.model_dump())


@app.post("/api/alerts/{alert_id}/ack", response_model=AlertAck)
async def api_alert_ack(alert_id: int, request: Request) -> JSONResponse:
    _verify_admin(request)
    ok = await db.acknowledge_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _no_cache(AlertAck(id=alert_id, acknowledged=True).model_dump())


@app.delete("/api/alerts")
async def api_alerts_delete(request: Request) -> JSONResponse:
    _verify_admin(request)
    deleted = await db.delete_alerts()
    return _no_cache({"deleted": deleted})


@app.get("/api/stats/summary", response_model=StatsSummary)
async def api_stats_summary() -> JSONResponse:
    tariff = await db.get_tariff()
    stats = await db.get_stats_summary(tariff_kes=tariff, uptime_pct=await _uptime_pct())
    return _no_cache(StatsSummary(**stats).model_dump())


@app.post("/api/config", response_model=ConfigResponse)
async def api_config_update(body: ConfigUpdate, request: Request) -> JSONResponse:
    _verify_admin(request)
    if body.tariff_kwh_cost is not None:
        await db.set_setting("tariff_kwh_cost", str(body.tariff_kwh_cost))
    if body.alert_threshold_ma is not None:
        await db.set_setting("alert_threshold_ma", str(body.alert_threshold_ma))
    return _no_cache((await _config_response()).model_dump())


@app.get("/api/config", response_model=ConfigResponse)
async def api_config_get() -> JSONResponse:
    return _no_cache((await _config_response()).model_dump())


@app.post("/api/blynk/webhook")
async def api_blynk_webhook(
    request: Request,
    secret: str = Query(""),
) -> JSONResponse:
    if not settings.ingest_secret or secret != settings.ingest_secret:
        raise HTTPException(status_code=401, detail="Invalid ingest secret")

    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON body") from exc

    try:
        reading = await ingest.ingest_webhook_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _no_cache(reading_to_api(reading))


@app.get("/api/blynk/test")
async def api_blynk_test() -> JSONResponse:
    try:
        async with httpx.AsyncClient() as client:
            pins = await ingest.fetch_blynk_pins(client)
        return _no_cache({"status": "ok", "pins": pins})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/cron/prune")
async def api_cron_prune(request: Request) -> JSONResponse:
    _verify_cron(request)
    if settings.retention_days <= 0:
        return _no_cache({"pruned": {"readings": 0, "alerts": 0}, "retention_days": 0})
    result = await db.prune_old_data(settings.retention_days)
    logger.info("cron_prune retention_days=%s result=%s", settings.retention_days, result)
    return _no_cache({"pruned": result, "retention_days": settings.retention_days})


# Legacy aliases
@app.get("/api/readings/latest")
async def legacy_latest() -> JSONResponse:
    return await api_latest()


@app.get("/api/readings/history")
async def legacy_history(
    hours: int = Query(24, ge=1, le=168),
) -> JSONResponse:
    rows = await db.get_readings_since(hours=hours)
    return _cached([reading_to_api(r) for r in rows], max_age=30)


@app.get("/api/settings", response_model=SettingsResponse)
async def legacy_settings_get() -> JSONResponse:
    token = settings.blynk_token.strip()
    stored = await db.get_setting("blynk_token", "")
    body = SettingsResponse(
        blynk_token_set=bool(token or stored),
        tariff_kwh_cost=round(await db.get_tariff(), 2),
        alert_threshold_ma=await db.get_alert_threshold_ma(),
        use_dummy_data=False,
        demo_mode=False,
        currency=settings.currency,
    )
    return _no_cache(body.model_dump())


@app.put("/api/settings", response_model=SettingsResponse)
async def legacy_settings_put(body: SettingsUpdate, request: Request) -> JSONResponse:
    _verify_admin(request)
    if body.tariff_kwh_cost is not None:
        await db.set_setting("tariff_kwh_cost", str(body.tariff_kwh_cost))
    if body.alert_threshold_ma is not None:
        await db.set_setting("alert_threshold_ma", str(body.alert_threshold_ma))
    if body.blynk_token is not None:
        await db.set_setting("blynk_token", body.blynk_token)
    return await legacy_settings_get()


@app.post("/api/alerts/{alert_id}/acknowledge", response_model=AlertAck)
async def legacy_alert_ack(alert_id: int, request: Request) -> JSONResponse:
    return await api_alert_ack(alert_id, request)


@app.get("/api/budget/estimate", response_model=BudgetEstimate)
async def legacy_budget(
    hours: int = Query(24, ge=1, le=720),
    cap_kwh: float | None = Query(None, ge=0),
) -> JSONResponse:
    energy = await db.get_energy_in_period(hours=hours)
    tariff = await db.get_tariff()
    cost = round(energy * tariff, 2)
    cap_cost = round(cap_kwh * tariff, 2) if cap_kwh is not None else None
    body = BudgetEstimate(
        energy_kwh=round(energy, 4),
        tariff_kwh_cost=round(tariff, 2),
        estimated_cost_kes=cost,
        cap_kwh=cap_kwh,
        cap_cost_kes=cap_cost,
        over_cap=cap_kwh is not None and energy > cap_kwh,
        currency=settings.currency,
    )
    return _cached(body.model_dump(), max_age=30)
