"""Push-based ingestion — webhook parsing, interval energy, noise-suppressed alerts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app import db
from app.config import settings
from app.models import Reading, ReadingCreate, WebhookPayload

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_blynk_body(body: str) -> list[float]:
    text = body.strip()
    if not text:
        raise ValueError("Empty Blynk response")

    values = [v.strip() for v in text.split("\0") if v.strip()]
    if len(values) == 1 and "," in values[0]:
        values = [v.strip() for v in values[0].split(",")]

    if len(values) < 6:
        raise ValueError(f"Expected 6 pin values (V0–V5), got {len(values)}: {text!r}")

    return [float(v) for v in values[:6]]


async def fetch_blynk_pins(client: httpx.AsyncClient) -> dict[str, Any]:
    """Single outbound Blynk REST fetch (for /api/blynk/test)."""
    token = settings.blynk_token.strip()
    if not token:
        raise ValueError("BLYNK_TOKEN is not configured")

    url = f"{settings.blynk_base_url}/get"
    query: list[tuple[str, str]] = [("token", token)]
    for pin in settings.blynk_pin_keys:
        query.append((pin, ""))

    response = await client.get(url, params=query, timeout=10.0)
    response.raise_for_status()
    v0, v1, v2, v3, v4, v5 = _parse_blynk_body(response.text)

    return {
        "voltage": v0,
        "current_in": v1,
        "current_out": v2,
        "real_power": v3,
        "energy_kwh_cumulative": v4,
        "hardware_alert": v5 >= 0.5,
    }


def _compute_interval(current_cumulative: float, previous: Optional[float]) -> float:
    if previous is None:
        return 0.0
    if current_cumulative < previous:
        return 0.0
    return max(0.0, current_cumulative - previous)


async def _should_raise_alert(differential_ma: float, hardware_alert: bool) -> bool:
    threshold = await db.get_alert_threshold_ma()
    if hardware_alert:
        return True
    if differential_ma <= threshold:
        return False

    n = max(1, settings.consecutive_samples)
    recent = await db.get_recent_differential_ma(n - 1)
    if len(recent) < n - 1:
        return False
    return all(value > threshold for value in recent)


async def ingest_snapshot(
    *,
    voltage: float,
    current_in: float,
    current_out: float,
    real_power: float,
    energy_kwh_cumulative: float,
    hardware_alert: bool = False,
    ts: Optional[datetime] = None,
) -> Reading:
    """
    Persist one complete device snapshot. All derived fields are computed server-side.
    """
    ts = ts or _utc_now()
    differential_ma = abs(current_in - current_out) * 1000.0
    previous = await db.get_previous_cumulative()
    interval_kwh = _compute_interval(energy_kwh_cumulative, previous)
    alert_triggered = await _should_raise_alert(differential_ma, hardware_alert)

    create = ReadingCreate(
        voltage=round(voltage, 3),
        current_in=round(current_in, 4),
        current_out=round(current_out, 4),
        differential_ma=round(differential_ma, 2),
        real_power=round(real_power, 2),
        energy_kwh_cumulative=round(energy_kwh_cumulative, 6),
        energy_kwh_interval=round(interval_kwh, 6),
        alert_triggered=alert_triggered,
    )
    await db.insert_reading(create, ts=ts)

    if alert_triggered:
        msg = (
            f"Power theft alert: differential {differential_ma:.0f} mA "
            f"(threshold {await db.get_alert_threshold_ma():.0f} mA)"
        )
        if hardware_alert:
            msg += "; hardware alert flag active"
        await db.insert_alert(differential_ma, msg, ts=ts)
        logger.warning(
            "theft_alert differential_ma=%.1f hardware=%s",
            differential_ma,
            hardware_alert,
        )

    return Reading(
        timestamp=ts,
        hardware_alert=hardware_alert,
        voltage=create.voltage,
        current_in=create.current_in,
        current_out=create.current_out,
        differential_current=create.differential_ma,
        real_power=create.real_power,
        energy_kwh=create.energy_kwh_cumulative,
        energy_kwh_interval=create.energy_kwh_interval,
        alert_triggered=alert_triggered,
    )


async def ingest_webhook(payload: WebhookPayload) -> Reading:
    return await ingest_snapshot(
        voltage=payload.voltage,
        current_in=payload.current_in,
        current_out=payload.current_out,
        real_power=payload.real_power,
        energy_kwh_cumulative=payload.energy_kwh_cumulative,
        hardware_alert=payload.hardware_alert,
    )


async def ingest_webhook_dict(data: dict[str, Any]) -> Reading:
    """Accept canonical JSON or Blynk virtual-pin keys (V0–V5 / v0–v5)."""
    normalized = _normalize_webhook_payload(data)
    payload = WebhookPayload(**normalized)
    return await ingest_webhook(payload)


def _pick_float(data: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        for candidate in (key, key.lower(), key.upper()):
            if candidate in data and data[candidate] not in (None, ""):
                return float(data[candidate])
    return None


def _normalize_webhook_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Map Blynk pin payloads or canonical field names to WebhookPayload kwargs."""
    voltage = _pick_float(data, "voltage", "V0", "v0")
    current_in = _pick_float(data, "current_in", "V1", "v1")
    current_out = _pick_float(data, "current_out", "V2", "v2")
    real_power = _pick_float(data, "real_power", "power", "V3", "v3")
    cumulative = _pick_float(
        data, "energy_kwh_cumulative", "energy_kwh", "energy", "V4", "v4"
    )

    hardware_raw = data.get("hardware_alert", data.get("V5", data.get("v5", 0)))
    hardware_alert = bool(float(hardware_raw) >= 0.5) if hardware_raw not in (None, "") else False

    missing = [
        name
        for name, val in (
            ("voltage", voltage),
            ("current_in", current_in),
            ("current_out", current_out),
            ("real_power", real_power),
            ("energy_kwh_cumulative", cumulative),
        )
        if val is None
    ]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    return {
        "voltage": voltage,
        "current_in": current_in,
        "current_out": current_out,
        "real_power": real_power,
        "energy_kwh_cumulative": cumulative,
        "hardware_alert": hardware_alert,
    }
