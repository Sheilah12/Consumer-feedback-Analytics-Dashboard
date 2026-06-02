"""Database persistence tests."""

import pytest

from app import db
from app.models import ReadingCreate


@pytest.mark.asyncio
async def test_insert_and_latest():
    await db.ensure_schema()
    rid = await db.insert_reading(
        ReadingCreate(
            voltage=230.0,
            current_in=5.0,
            current_out=4.8,
            differential_ma=200.0,
            real_power=1100.0,
            energy_kwh_cumulative=1.5,
            energy_kwh_interval=0.01,
            alert_triggered=False,
        )
    )
    assert rid > 0
    latest = await db.get_latest_reading()
    assert latest is not None
    assert latest.voltage == 230.0
