#!/usr/bin/env python3
"""Create Postgres schema (idempotent). Run once against Neon."""

from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.db import SCHEMA, connect  # noqa: E402


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("Set DATABASE_URL to your Neon pooled connection string.", file=sys.stderr)
        sys.exit(1)

    async with connect() as conn:
        await conn.execute(SCHEMA)
        defaults = {
            "tariff_kwh_cost": os.environ.get("TARIFF_KWH_COST", "25.0"),
            "alert_threshold_ma": os.environ.get("ALERT_THRESHOLD_MA", "150"),
        }
        for key, value in defaults.items():
            await conn.execute(
                "INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                key,
                value,
            )
    print("Schema migrated successfully.")


if __name__ == "__main__":
    asyncio.run(main())
