"""Map internal models to REST JSON contracts (UTC ISO, A, KES)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.models import Alert, Reading


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _round4(value: float) -> float:
    return round(float(value), 4)


def _round2_kes(value: float) -> float:
    return round(float(value), 2)


def reading_to_api(row: Reading | dict[str, Any]) -> dict[str, Any]:
    """API reading: currents in A (4 dp), differential in A, energy 4 dp, UTC timestamp."""
    if isinstance(row, Reading):
        ts = row.timestamp
        voltage = row.voltage
        current_in = row.current_in
        current_out = row.current_out
        diff_ma = row.differential_current
        real_power = row.real_power
        energy_kwh = row.energy_kwh
        alert_triggered = row.alert_triggered
        hardware_alert = row.hardware_alert
    else:
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        voltage = row["voltage"]
        current_in = row["current_in"]
        current_out = row["current_out"]
        diff_ma = row["differential_current"]
        real_power = row["real_power"]
        energy_kwh = row["energy_kwh"]
        alert_triggered = bool(row.get("alert_triggered", 0))
        hardware_alert = bool(row.get("hardware_alert", False))

    diff_a = diff_ma / 1000.0

    return {
        "timestamp": _iso_utc(ts),
        "voltage": _round4(voltage),
        "current_in": _round4(current_in),
        "current_out": _round4(current_out),
        "differential_current": _round4(diff_a),
        "real_power": _round4(real_power),
        "energy_kwh": _round4(energy_kwh),
        "alert_triggered": alert_triggered,
        "hardware_alert": hardware_alert,
    }


def alert_to_api(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "timestamp": _iso_utc(alert.timestamp),
        "differential_ma": round(alert.differential_ma, 2),
        "differential_current": _round4(alert.differential_ma / 1000.0),
        "message": alert.message,
        "acknowledged": alert.acknowledged,
    }
