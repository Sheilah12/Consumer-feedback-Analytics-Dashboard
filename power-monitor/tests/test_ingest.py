"""Ingestion pipeline tests."""

import pytest

from app import ingest
from app.ingest import _compute_interval, _parse_blynk_body
from app.stream_fields import (
    SYSTEM_ALERT,
    SYSTEM_ISOLATED,
    SYSTEM_NORMAL,
    derive_status_from_differential,
    is_tier_transition,
    map_device_status,
    resolve_system_status,
    tier_for_status,
)


@pytest.mark.unit
def test_parse_blynk_body_csv():
    values = _parse_blynk_body("220.5,4.1,4.0,900.0,12.5,0")
    assert len(values) == 6
    assert values[0] == 220.5


@pytest.mark.unit
def test_compute_interval_normal():
    assert _compute_interval(101.0, 100.0) == pytest.approx(1.0)


@pytest.mark.unit
def test_compute_interval_reboot():
    assert _compute_interval(50.0, 100.0) == 0.0


@pytest.mark.unit
def test_map_device_status_tiers():
    assert map_device_status("normal") == SYSTEM_NORMAL
    assert map_device_status("alert") == SYSTEM_ALERT
    assert map_device_status("investigation") == SYSTEM_ALERT
    assert map_device_status("isolated") == SYSTEM_ISOLATED
    assert map_device_status("theft") == SYSTEM_ISOLATED


@pytest.mark.unit
def test_derive_status_from_differential_bands():
    assert derive_status_from_differential(50, 100, 300) == SYSTEM_NORMAL
    assert derive_status_from_differential(150, 100, 300) == SYSTEM_ALERT
    assert derive_status_from_differential(350, 100, 300) == SYSTEM_ISOLATED


@pytest.mark.unit
def test_resolve_system_status_device_authoritative():
    status, hw = resolve_system_status("isolated", 50, 100, 300)
    assert status == SYSTEM_ISOLATED
    assert hw is True


@pytest.mark.unit
def test_tier_transition():
    assert is_tier_transition(SYSTEM_NORMAL, SYSTEM_ALERT) is True
    assert is_tier_transition(SYSTEM_ALERT, SYSTEM_ISOLATED) is True
    assert is_tier_transition(SYSTEM_ISOLATED, SYSTEM_ISOLATED) is False
    assert tier_for_status(SYSTEM_ISOLATED) == "isolation"


@pytest.mark.unit
def test_normalize_blynk_pin_payload():
    from app.ingest import _normalize_webhook_payload

    out = _normalize_webhook_payload(
        {"V0": 220, "V1": 4.1, "V2": 4.0, "V3": 900, "V4": 12.5, "V5": 0}
    )
    assert out["voltage"] == 220
    assert out["current_in"] == 4.1
    assert out["energy_kwh_cumulative"] == 12.5


@pytest.mark.unit
def test_normalize_blynk_stream_payload():
    from app.ingest import _normalize_webhook_payload

    out = _normalize_webhook_payload(
        {
            "live_current": 4.123,
            "neutral_current": 4.118,
            "differential": 0.005,
            "voltage": 229.4,
            "real_power": 945.2,
            "energy_kwh_cumulative": 1234.5,
            "system_status": "normal",
            "ts": "2026-05-30T12:00:00.000Z",
        }
    )
    assert out["current_in"] == pytest.approx(4.123)
    assert out["current_out"] == pytest.approx(4.118)
    assert out["differential_ma"] == pytest.approx(5.0, rel=0.01)
    assert out["system_status"] == "normal"
    assert out["ts"] is not None


@pytest.mark.asyncio
async def test_ingest_snapshot():
    reading = await ingest.ingest_snapshot(
        voltage=230.0,
        current_in=5.0,
        current_out=4.85,
        real_power=1050.0,
        energy_kwh_cumulative=1.0,
    )
    assert reading.differential_current == pytest.approx(150.0, rel=0.01)
    assert reading.energy_kwh == pytest.approx(1.0)
    assert reading.system_status == SYSTEM_ALERT
