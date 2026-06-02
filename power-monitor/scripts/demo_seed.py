#!/usr/bin/env python3
"""Seed Neon with historical demo readings via the ingest pipeline."""

from __future__ import annotations

import asyncio
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import ingest  # noqa: E402
from app.db import ensure_schema  # noqa: E402


async def seed(hours: int = 48, step_seconds: int = 30) -> None:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("Set DATABASE_URL before running demo_seed.", file=sys.stderr)
        sys.exit(1)

    await ensure_schema()
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    cumulative = 1000.0
    ts = start

    count = 0
    while ts <= now:
        hour_frac = ts.hour + ts.minute / 60.0
        load = 1.2 if 18 <= hour_frac < 22 else 0.7
        voltage = 220.0 + 1.5 * math.sin(ts.timestamp() / 45.0)
        amps = 3.0 * load + 0.2 * math.sin(ts.timestamp() / 18.0)
        current_in = amps + random.uniform(-0.02, 0.02)
        current_out = current_in - random.uniform(0.003, 0.012)
        power = max(0.0, voltage * min(current_in, current_out))
        cumulative += (power / 1000.0) * (step_seconds / 3600.0)

        await ingest.ingest_snapshot(
            voltage=voltage,
            current_in=current_in,
            current_out=current_out,
            real_power=power,
            energy_kwh_cumulative=cumulative,
            hardware_alert=False,
            ts=ts,
        )
        count += 1
        ts += timedelta(seconds=step_seconds)

    print(f"Seeded {count} readings from {start.isoformat()} to {now.isoformat()}.")


if __name__ == "__main__":
    hours = int(os.environ.get("SEED_HOURS", "48"))
    step = int(os.environ.get("SEED_STEP_SECONDS", "30"))
    asyncio.run(seed(hours=hours, step_seconds=step))
