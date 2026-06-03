"""Neon Postgres data access via asyncpg — short-lived connections per request."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import asyncpg

from app.config import settings
from app.models import Alert, DailyBucket, HourlyBucket, Reading, ReadingCreate

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    voltage DOUBLE PRECISION,
    current_in DOUBLE PRECISION,
    current_out DOUBLE PRECISION,
    differential_ma DOUBLE PRECISION,
    real_power DOUBLE PRECISION,
    energy_kwh_cumulative DOUBLE PRECISION,
    energy_kwh_interval DOUBLE PRECISION,
    alert_triggered BOOLEAN DEFAULT false,
    system_status TEXT,
    hardware_alert BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (ts DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    differential_ma DOUBLE PRECISION,
    message TEXT,
    acknowledged BOOLEAN DEFAULT false,
    cleared_at TIMESTAMPTZ,
    tier TEXT,
    system_status TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts (ts DESC);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

MIGRATIONS = (
    "ALTER TABLE readings ADD COLUMN IF NOT EXISTS system_status TEXT",
    "ALTER TABLE readings ADD COLUMN IF NOT EXISTS hardware_alert BOOLEAN DEFAULT false",
    "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS tier TEXT",
    "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS system_status TEXT",
)

READING_SELECT = """
    ts, voltage, current_in, current_out, differential_ma,
    real_power, energy_kwh_cumulative, energy_kwh_interval,
    alert_triggered, system_status, hardware_alert
"""

ALERT_SELECT = """
    id, ts, differential_ma, message, acknowledged, cleared_at, tier, system_status
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_db() -> str:
    url = settings.database_url.strip() or os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


@asynccontextmanager
async def connect() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_require_db())
    try:
        yield conn
    finally:
        await conn.close()


async def ensure_schema() -> None:
    """Idempotent schema + default config seed (safe on cold start)."""
    async with connect() as conn:
        await conn.execute(SCHEMA)
        for stmt in MIGRATIONS:
            await conn.execute(stmt)
        defaults = {
            "tariff_kwh_cost": str(settings.tariff_kwh_cost),
            "alert_threshold_ma": str(settings.alert_threshold_ma),
            "isolation_threshold_ma": str(settings.isolation_threshold_ma),
            "monthly_budget_kes": str(settings.monthly_budget_kes),
        }
        for key, value in defaults.items():
            await conn.execute(
                "INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                key,
                value,
            )


async def get_setting(key: str, default: str = "") -> str:
    await ensure_schema()
    async with connect() as conn:
        row = await conn.fetchrow("SELECT value FROM config WHERE key = $1", key)
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await ensure_schema()
    async with connect() as conn:
        await conn.execute(
            """
            INSERT INTO config (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            key,
            value,
        )


async def get_tariff() -> float:
    raw = await get_setting("tariff_kwh_cost", str(settings.tariff_kwh_cost))
    return float(raw)


async def get_alert_threshold_ma() -> float:
    raw = await get_setting("alert_threshold_ma", str(settings.alert_threshold_ma))
    return float(raw)


async def get_isolation_threshold_ma() -> float:
    raw = await get_setting("isolation_threshold_ma", str(settings.isolation_threshold_ma))
    return float(raw)


async def get_monthly_budget_kes() -> float:
    raw = await get_setting("monthly_budget_kes", str(settings.monthly_budget_kes))
    return float(raw)


async def get_month_to_date_kwh() -> float:
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(energy_kwh_interval), 0) AS kwh
            FROM readings
            WHERE ts >= date_trunc('month', now())
            """
        )
    return float(row["kwh"] if row else 0.0)


async def get_month_daily_energy() -> list[dict[str, Any]]:
    """Daily kWh totals for the current UTC calendar month."""
    async with connect() as conn:
        rows = await conn.fetch(
            """
            SELECT
                (ts AT TIME ZONE 'UTC')::date AS day,
                COALESCE(SUM(energy_kwh_interval), 0) AS energy_kwh
            FROM readings
            WHERE ts >= date_trunc('month', now())
            GROUP BY 1
            ORDER BY day ASC
            """
        )
    return [
        {"day": row["day"].isoformat(), "energy_kwh": round(float(row["energy_kwh"]), 4)}
        for row in rows
    ]


async def get_latest_system_status() -> Optional[str]:
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            SELECT system_status
            FROM readings
            ORDER BY ts DESC, id DESC
            LIMIT 1
            """
        )
    if not row or row["system_status"] is None:
        return None
    return str(row["system_status"])


async def get_previous_cumulative() -> Optional[float]:
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            SELECT energy_kwh_cumulative
            FROM readings
            ORDER BY ts DESC, id DESC
            LIMIT 1
            """
        )
    if not row or row["energy_kwh_cumulative"] is None:
        return None
    return float(row["energy_kwh_cumulative"])


async def get_recent_differential_ma(limit: int) -> list[float]:
    if limit <= 0:
        return []
    async with connect() as conn:
        rows = await conn.fetch(
            """
            SELECT differential_ma
            FROM readings
            ORDER BY ts DESC, id DESC
            LIMIT $1
            """,
            limit,
        )
    return [float(r["differential_ma"]) for r in rows]


async def insert_reading(data: ReadingCreate, ts: Optional[datetime] = None) -> int:
    await ensure_schema()
    ts = ts or _utc_now()
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO readings (
                ts, voltage, current_in, current_out, differential_ma,
                real_power, energy_kwh_cumulative, energy_kwh_interval,
                alert_triggered, system_status, hardware_alert
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
            """,
            ts,
            data.voltage,
            data.current_in,
            data.current_out,
            data.differential_ma,
            data.real_power,
            data.energy_kwh_cumulative,
            data.energy_kwh_interval,
            data.alert_triggered,
            data.system_status,
            data.hardware_alert,
        )
    return int(row["id"])


async def insert_alert(
    differential_ma: float,
    message: str,
    *,
    tier: str,
    system_status: str,
    ts: Optional[datetime] = None,
) -> int:
    await ensure_schema()
    ts = ts or _utc_now()
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO alerts (ts, differential_ma, message, acknowledged, tier, system_status)
            VALUES ($1, $2, $3, false, $4, $5)
            RETURNING id
            """,
            ts,
            differential_ma,
            message,
            tier,
            system_status,
        )
    return int(row["id"])


async def get_latest_reading() -> Optional[Reading]:
    async with connect() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT {READING_SELECT}
            FROM readings
            ORDER BY ts DESC, id DESC
            LIMIT 1
            """
        )
    return _row_to_reading(row) if row else None


async def get_last_ingest_ts() -> Optional[datetime]:
    async with connect() as conn:
        row = await conn.fetchrow("SELECT MAX(ts) AS ts FROM readings")
    if not row or row["ts"] is None:
        return None
    return row["ts"]


async def get_readings_since(hours: int = 24, limit: int = 5000) -> list[Reading]:
    async with connect() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {READING_SELECT}
            FROM readings
            WHERE ts >= now() - ($1::text || ' hours')::interval
            ORDER BY ts ASC
            LIMIT $2
            """,
            str(hours),
            limit,
        )
    return [_row_to_reading(r) for r in rows]


async def get_energy_in_period(hours: int = 24) -> float:
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(energy_kwh_interval), 0) AS delta_kwh
            FROM readings
            WHERE ts >= now() - ($1::text || ' hours')::interval
            """,
            str(hours),
        )
    return float(row["delta_kwh"] if row else 0.0)


async def count_readings(
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> int:
    clauses: list[str] = []
    params: list[Any] = []
    idx = 1
    if from_iso:
        clauses.append(f"ts >= ${idx}")
        params.append(_parse_iso(from_iso))
        idx += 1
    if to_iso:
        clauses.append(f"ts <= ${idx}")
        params.append(_parse_iso(to_iso))
        idx += 1
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with connect() as conn:
        row = await conn.fetchrow(f"SELECT COUNT(*) AS n FROM readings {where}", *params)
    return int(row["n"] if row else 0)


async def get_readings_paginated(
    limit: int = 100,
    offset: int = 0,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> list[Reading]:
    clauses: list[str] = []
    params: list[Any] = []
    idx = 1
    if from_iso:
        clauses.append(f"ts >= ${idx}")
        params.append(_parse_iso(from_iso))
        idx += 1
    if to_iso:
        clauses.append(f"ts <= ${idx}")
        params.append(_parse_iso(to_iso))
        idx += 1
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    async with connect() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {READING_SELECT}
            FROM readings
            {where}
            ORDER BY ts DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )
    return [_row_to_reading(r) for r in rows]


async def get_readings_hourly(
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> list[HourlyBucket]:
    """Hourly aggregates; zero-filled 24 buckets per day in range via generate_series."""
    from_dt = _parse_iso(from_iso) if from_iso else None
    to_dt = _parse_iso(to_iso) if to_iso else None

    async with connect() as conn:
        rows = await conn.fetch(
            """
            WITH bounds AS (
                SELECT
                    COALESCE($1::timestamptz, now() - interval '7 days') AS start_ts,
                    COALESCE($2::timestamptz, now()) AS end_ts
            ),
            hours AS (
                SELECT generate_series(
                    date_trunc('hour', (SELECT start_ts FROM bounds)),
                    date_trunc('hour', (SELECT end_ts FROM bounds)),
                    interval '1 hour'
                ) AS hour
            ),
            agg AS (
                SELECT
                    date_trunc('hour', r.ts) AS hour,
                    COALESCE(SUM(r.energy_kwh_interval), 0) AS energy_kwh,
                    AVG(r.voltage) AS avg_voltage,
                    AVG(r.current_in) AS avg_current_in,
                    AVG(r.current_out) AS avg_current_out,
                    AVG(r.differential_ma) AS avg_differential_ma,
                    AVG(r.real_power) AS avg_real_power,
                    MAX(r.real_power) AS max_real_power,
                    COUNT(*) AS sample_count
                FROM readings r, bounds b
                WHERE r.ts >= b.start_ts AND r.ts <= b.end_ts
                GROUP BY 1
            )
            SELECT
                to_char(h.hour AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:00:00"Z"') AS hour,
                to_char(h.hour AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day,
                EXTRACT(HOUR FROM h.hour AT TIME ZONE 'UTC')::int AS hour_of_day,
                COALESCE(a.energy_kwh, 0) AS energy_kwh,
                COALESCE(a.avg_voltage, 0) AS avg_voltage,
                COALESCE(a.avg_current_in, 0) AS avg_current_in,
                COALESCE(a.avg_current_out, 0) AS avg_current_out,
                COALESCE(a.avg_differential_ma, 0) AS avg_differential_ma,
                COALESCE(a.avg_real_power, 0) AS avg_real_power,
                COALESCE(a.max_real_power, 0) AS max_real_power,
                COALESCE(a.sample_count, 0)::int AS sample_count
            FROM hours h
            LEFT JOIN agg a ON a.hour = h.hour
            ORDER BY h.hour ASC
            """,
            from_dt,
            to_dt,
        )

    return [
        HourlyBucket(
            hour=row["hour"],
            day=row["day"],
            hour_of_day=int(row["hour_of_day"]),
            energy_kwh=round(float(row["energy_kwh"]), 4),
            avg_voltage=round(float(row["avg_voltage"]), 4),
            avg_current_in=round(float(row["avg_current_in"]), 4),
            avg_current_out=round(float(row["avg_current_out"]), 4),
            avg_differential_current=round(float(row["avg_differential_ma"]) / 1000.0, 4),
            avg_real_power=round(float(row["avg_real_power"]), 4),
            max_real_power=round(float(row["max_real_power"]), 4),
            sample_count=int(row["sample_count"]),
        )
        for row in rows
    ]


async def get_readings_daily(
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> list[DailyBucket]:
    from_dt = _parse_iso(from_iso) if from_iso else None
    to_dt = _parse_iso(to_iso) if to_iso else None

    async with connect() as conn:
        rows = await conn.fetch(
            """
            SELECT
                (ts AT TIME ZONE 'UTC')::date AS day,
                COALESCE(SUM(energy_kwh_interval), 0) AS energy_kwh,
                AVG(real_power) AS avg_power,
                MAX(GREATEST(current_in, current_out)) AS peak_current,
                COUNT(*)::int AS sample_count
            FROM readings
            WHERE ($1::timestamptz IS NULL OR ts >= $1)
              AND ($2::timestamptz IS NULL OR ts <= $2)
              AND ($1::timestamptz IS NOT NULL OR ts >= now() - interval '30 days')
            GROUP BY 1
            ORDER BY day ASC
            """,
            from_dt,
            to_dt,
        )

    return [
        DailyBucket(
            day=row["day"].isoformat(),
            energy_kwh=round(float(row["energy_kwh"]), 4),
            avg_power=round(float(row["avg_power"] or 0), 4),
            peak_current=round(float(row["peak_current"] or 0), 4),
            sample_count=int(row["sample_count"]),
        )
        for row in rows
    ]


async def count_alerts(acknowledged: Optional[bool] = None) -> int:
    async with connect() as conn:
        if acknowledged is None:
            row = await conn.fetchrow("SELECT COUNT(*) AS n FROM alerts")
        else:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM alerts WHERE acknowledged = $1",
                acknowledged,
            )
    return int(row["n"] if row else 0)


async def get_alerts_paginated(
    limit: int = 100,
    offset: int = 0,
    acknowledged: Optional[bool] = None,
) -> list[Alert]:
    async with connect() as conn:
        if acknowledged is None:
            rows = await conn.fetch(
                f"""
                SELECT {ALERT_SELECT}
                FROM alerts
                ORDER BY id DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT {ALERT_SELECT}
                FROM alerts
                WHERE acknowledged = $1
                ORDER BY id DESC
                LIMIT $2 OFFSET $3
                """,
                acknowledged,
                limit,
                offset,
            )
    return [_row_to_alert(r) for r in rows]


async def acknowledge_alert(alert_id: int) -> bool:
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            UPDATE alerts SET acknowledged = true
            WHERE id = $1
            RETURNING id
            """,
            alert_id,
        )
    return row is not None


async def delete_alerts() -> int:
    async with connect() as conn:
        result = await conn.execute("DELETE FROM alerts")
    return int(result.split()[-1])


async def get_stats_summary(tariff_kes: float, uptime_pct: float) -> dict[str, Any]:
    async with connect() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (
                    SELECT COALESCE(SUM(energy_kwh_interval), 0)
                    FROM readings
                    WHERE (ts AT TIME ZONE 'UTC')::date = (now() AT TIME ZONE 'UTC')::date
                ) AS today_kwh,
                (
                    SELECT COALESCE(SUM(energy_kwh_interval), 0)
                    FROM readings
                    WHERE ts >= date_trunc('month', now())
                ) AS month_kwh,
                (
                    SELECT COUNT(*)
                    FROM alerts
                    WHERE (ts AT TIME ZONE 'UTC')::date = (now() AT TIME ZONE 'UTC')::date
                ) AS alert_count_today
            """
        )

    today_kwh = round(float(row["today_kwh"] or 0), 4)
    month_kwh = round(float(row["month_kwh"] or 0), 4)
    return {
        "today_kwh": today_kwh,
        "month_kwh": month_kwh,
        "month_cost_kes": round(month_kwh * tariff_kes, 2),
        "alert_count_today": int(row["alert_count_today"] or 0),
        "uptime_pct": round(uptime_pct, 2),
    }


async def get_db_size_bytes() -> Optional[int]:
    async with connect() as conn:
        row = await conn.fetchrow("SELECT pg_database_size(current_database()) AS size")
    return int(row["size"]) if row else None


async def prune_old_data(retention_days: int) -> dict[str, int]:
    if retention_days <= 0:
        return {"readings": 0, "alerts": 0}
    async with connect() as conn:
        r1 = await conn.execute(
            """
            DELETE FROM readings
            WHERE ts < now() - ($1::text || ' days')::interval
            """,
            str(retention_days),
        )
        r2 = await conn.execute(
            """
            DELETE FROM alerts
            WHERE ts < now() - ($1::text || ' days')::interval
            """,
            str(retention_days),
        )
    return {
        "readings": int(r1.split()[-1]),
        "alerts": int(r2.split()[-1]),
    }


async def check_db_ok() -> bool:
    if not settings.has_database:
        return False
    try:
        async with connect() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as exc:
        logger.warning("db_health_failed: %s", exc)
        return False


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_to_reading(row: asyncpg.Record) -> Reading:
    return Reading(
        timestamp=row["ts"],
        voltage=float(row["voltage"]),
        current_in=float(row["current_in"]),
        current_out=float(row["current_out"]),
        differential_current=float(row["differential_ma"]),
        real_power=float(row["real_power"]),
        energy_kwh=float(row["energy_kwh_cumulative"]),
        energy_kwh_interval=float(row["energy_kwh_interval"] or 0),
        alert_triggered=bool(row["alert_triggered"]),
        hardware_alert=bool(row["hardware_alert"]),
        system_status=str(row["system_status"] or "normal"),
    )


def _row_to_alert(row: asyncpg.Record) -> Alert:
    return Alert(
        id=int(row["id"]),
        timestamp=row["ts"],
        differential_ma=float(row["differential_ma"]),
        message=row["message"],
        acknowledged=bool(row["acknowledged"]),
        cleared_at=row["cleared_at"],
        tier=row["tier"],
        system_status=row["system_status"],
    )
