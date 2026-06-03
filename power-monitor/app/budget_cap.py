"""Monthly budget cap calculations (pure functions for tests and API)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional


def compute_budget_cap(
    *,
    now: datetime,
    month_to_date_kwh: float,
    tariff_kwh_cost: float,
    monthly_budget_kes: float,
) -> dict[str, Any]:
    """Project month-end spend and cap exhaustion from month-to-date usage."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    year = now.year
    month = now.month
    days_in_month = monthrange(year, month)[1]
    days_elapsed = max(1, now.day)
    days_remaining = max(0, days_in_month - days_elapsed)

    month_to_date_kwh = round(float(month_to_date_kwh), 4)
    tariff = float(tariff_kwh_cost)
    budget = float(monthly_budget_kes)
    month_to_date_cost = round(month_to_date_kwh * tariff, 2)

    pct_used = round((month_to_date_cost / budget) * 100.0, 2) if budget > 0 else 0.0
    projected_month_cost = round((month_to_date_cost / days_elapsed) * days_in_month, 2)
    remaining_kes = round(budget - month_to_date_cost, 2)
    daily_allowance_remaining = (
        round(remaining_kes / days_remaining, 2) if days_remaining > 0 else 0.0
    )
    on_track = projected_month_cost <= budget if budget > 0 else True
    projected_overage = round(max(0.0, projected_month_cost - budget), 2)

    est_exhaustion_date: Optional[str] = None
    daily_rate = month_to_date_cost / days_elapsed
    if daily_rate > 0 and remaining_kes > 0:
        days_until = remaining_kes / daily_rate
        exhaust: date = now.date() + timedelta(days=days_until)
        est_exhaustion_date = exhaust.isoformat()

    return {
        "month_to_date_kwh": month_to_date_kwh,
        "month_to_date_cost": month_to_date_cost,
        "monthly_budget_kes": round(budget, 2),
        "tariff_kwh_cost": round(tariff, 2),
        "pct_used": pct_used,
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "days_remaining": days_remaining,
        "projected_month_cost": projected_month_cost,
        "remaining_kes": remaining_kes,
        "daily_allowance_remaining": daily_allowance_remaining,
        "on_track": on_track,
        "projected_overage": projected_overage,
        "est_exhaustion_date": est_exhaustion_date,
        "currency": "KES",
    }
