"""Map internal models to REST JSON contracts (Blynk stream names + legacy aliases)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.models import Alert, Reading
from app.stream_fields import tier_for_status


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _round4(value: float) -> float:
    return round(float(value), 4)


def reading_to_api(row: Reading | dict[str, Any]) -> dict[str, Any]:
    """Primary keys match Blynk streams; legacy keys kept for older clients."""
    if isinstance(row, Reading):
        ts = row.timestamp
        voltage = row.voltage
        live = row.current_in
        neutral = row.current_out
        diff_ma = row.differential_current
        real_power = row.real_power
        energy = row.energy_kwh
        alert_triggered = row.alert_triggered
        hardware_alert = row.hardware_alert
        status = row.system_status
    else:
        ts = row.get("ts") or row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        voltage = row["voltage"]
        live = row.get("live_current", row["current_in"])
        neutral = row.get("neutral_current", row["current_out"])
        diff_ma = row.get("differential_ma", row["differential_current"])
        if diff_ma is not None and diff_ma < 5:
            diff_ma = float(diff_ma) * 1000.0
        real_power = row["real_power"]
        energy = row.get("energy_kwh_cumulative", row["energy_kwh"])
        alert_triggered = bool(row.get("alert_triggered", 0))
        hardware_alert = bool(row.get("hardware_alert", False))
        status = str(row.get("system_status") or "normal")

    diff_a = float(diff_ma) / 1000.0
    ts_iso = _iso_utc(ts)
    tier = tier_for_status(status)

    return {
        "ts": ts_iso,
        "timestamp": ts_iso,
        "live_current": _round4(live),
        "neutral_current": _round4(neutral),
        "differential": _round4(diff_a),
        "voltage": _round4(voltage),
        "real_power": _round4(real_power),
        "energy_kwh_cumulative": _round4(energy),
        "system_status": status,
        "tier": tier,
        "alert_triggered": alert_triggered,
        "hardware_alert": hardware_alert,
        # Legacy aliases
        "current_in": _round4(live),
        "current_out": _round4(neutral),
        "differential_current": _round4(diff_a),
        "differential_ma": round(float(diff_ma), 2),
        "energy_kwh": _round4(energy),
    }


def alert_to_api(alert: Alert) -> dict[str, Any]:
    status = alert.system_status or "alert"
    return {
        "id": alert.id,
        "ts": _iso_utc(alert.timestamp),
        "timestamp": _iso_utc(alert.timestamp),
        "differential": _round4(alert.differential_ma / 1000.0),
        "differential_ma": round(alert.differential_ma, 2),
        "differential_current": _round4(alert.differential_ma / 1000.0),
        "message": alert.message,
        "acknowledged": alert.acknowledged,
        "tier": alert.tier,
        "system_status": status,
    }
