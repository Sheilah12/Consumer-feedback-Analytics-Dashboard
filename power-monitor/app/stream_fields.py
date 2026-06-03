"""Blynk / API field names and two-tier system_status resolution."""

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

SYSTEM_NORMAL = "normal"
SYSTEM_ALERT = "alert"
SYSTEM_ISOLATED = "isolated"

TIER_INVESTIGATION = "investigation"
TIER_ISOLATION = "isolation"


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


def differential_to_ma(value: float) -> float:
    """Device may send differential in A (< ~5) or mA."""
    if abs(value) < 5:
        return abs(value) * 1000.0
    return abs(value)


def map_device_status(raw: Any) -> str:
    """Map device-reported status to normal | alert | isolated."""
    if raw is None or raw == "":
        return SYSTEM_NORMAL
    if isinstance(raw, (int, float)):
        if float(raw) >= 2:
            return SYSTEM_ISOLATED
        if float(raw) >= 0.5:
            return SYSTEM_ALERT
        return SYSTEM_NORMAL
    text = str(raw).strip().lower().replace("-", " ").replace("/", " ")
    if text in (SYSTEM_ISOLATED, "isolation", "theft", "trip", "tripped", "fault"):
        return SYSTEM_ISOLATED
    if text in (
        SYSTEM_ALERT,
        "investigation",
        "investigate",
        "warning",
        "suspect",
        "abnormal",
        "1",
        "true",
        "yes",
        "on",
    ):
        return SYSTEM_ALERT
    return SYSTEM_NORMAL


def derive_status_from_differential(
    differential_ma: float,
    alert_threshold_ma: float,
    isolation_threshold_ma: float,
) -> str:
    """Cloud backstop when device omits system_status."""
    if differential_ma >= isolation_threshold_ma:
        return SYSTEM_ISOLATED
    if differential_ma >= alert_threshold_ma:
        return SYSTEM_ALERT
    return SYSTEM_NORMAL


def resolve_system_status(
    device_raw: Any,
    differential_ma: float,
    alert_threshold_ma: float,
    isolation_threshold_ma: float,
) -> tuple[str, bool]:
    """
    Device status is authoritative when present; otherwise derive from differential bands.
    hardware_alert is True only for isolated (relay tripped at device).
    """
    if device_raw is not None and device_raw != "":
        status = map_device_status(device_raw)
    else:
        status = derive_status_from_differential(
            differential_ma, alert_threshold_ma, isolation_threshold_ma
        )
    hardware_alert = status == SYSTEM_ISOLATED
    return status, hardware_alert


def tier_for_status(status: str) -> Optional[str]:
    if status == SYSTEM_ALERT:
        return TIER_INVESTIGATION
    if status == SYSTEM_ISOLATED:
        return TIER_ISOLATION
    return None


def status_severity(status: str) -> int:
    return {SYSTEM_NORMAL: 0, SYSTEM_ALERT: 1, SYSTEM_ISOLATED: 2}.get(status, 0)


def is_tier_transition(previous: Optional[str], current: str) -> bool:
    """True when entering alert or isolated from a lower severity."""
    if current not in (SYSTEM_ALERT, SYSTEM_ISOLATED):
        return False
    prev = previous or SYSTEM_NORMAL
    return status_severity(current) > status_severity(prev)


def alert_message(status: str, differential_ma: float, tier: str) -> str:
    if status == SYSTEM_ISOLATED:
        return (
            f"Power theft isolation: differential {differential_ma:.0f} mA — "
            "relay tripped; manual reset required at device"
        )
    return (
        f"Investigation alert: differential {differential_ma:.0f} mA — "
        "human review required, no disconnection"
    )
