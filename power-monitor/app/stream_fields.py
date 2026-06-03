"""Blynk / API field names for the seven data streams + device timestamp."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Canonical names (Blynk webhook template)
STREAM_LIVE_CURRENT = "live_current"
STREAM_NEUTRAL_CURRENT = "neutral_current"
STREAM_DIFFERENTIAL = "differential"
STREAM_VOLTAGE = "voltage"
STREAM_REAL_POWER = "real_power"
STREAM_ENERGY = "energy_kwh_cumulative"
STREAM_SYSTEM_STATUS = "system_status"
STREAM_TS = "ts"


def pick_float(data: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        for candidate in (key, key.lower(), key.upper()):
            if candidate in data and data[candidate] not in (None, ""):
                return float(data[candidate])
    return None


def parse_device_ts(data: dict[str, Any]) -> Optional[datetime]:
    raw = data.get(STREAM_TS) or data.get("timestamp")
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_system_status(raw: Any) -> bool:
    """True when device reports alert / theft / fault."""
    if raw is None or raw == "":
        return False
    if isinstance(raw, (int, float)):
        return float(raw) >= 0.5
    text = str(raw).strip().lower()
    return text in (
        "alert",
        "theft",
        "fault",
        "abnormal",
        "1",
        "true",
        "yes",
        "on",
    )


def differential_to_ma(value: float) -> float:
    """Device may send differential in A (< ~5) or mA."""
    if abs(value) < 5:
        return abs(value) * 1000.0
    return abs(value)


def system_status_label(alert_triggered: bool, hardware_alert: bool = False) -> str:
    if alert_triggered or hardware_alert:
        return "alert"
    return "normal"
