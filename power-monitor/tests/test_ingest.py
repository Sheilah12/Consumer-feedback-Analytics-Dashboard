"""Ingestion pipeline tests."""

import pytest

from app import ingest
from app.ingest import _compute_interval, _parse_blynk_body


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
def test_normalize_blynk_pin_payload():
    from app.ingest import _normalize_webhook_payload

    out = _normalize_webhook_payload(
        {"V0": 220, "V1": 4.1, "V2": 4.0, "V3": 900, "V4": 12.5, "V5": 0}
    )
    assert out["voltage"] == 220
    assert out["current_in"] == 4.1
    assert out["energy_kwh_cumulative"] == 12.5


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
