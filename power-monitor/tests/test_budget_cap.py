"""Unit tests for monthly budget cap calculations."""

from datetime import datetime, timezone

import pytest

from app.budget_cap import compute_budget_cap


@pytest.mark.unit
def test_mid_month_on_track():
    # 15th of a 30-day month, half budget spent proportionally
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    result = compute_budget_cap(
        now=now,
        month_to_date_kwh=50.0,
        tariff_kwh_cost=25.0,
        monthly_budget_kes=3000.0,
    )
    assert result["month_to_date_cost"] == pytest.approx(1250.0)
    assert result["days_elapsed"] == 15
    assert result["days_in_month"] == 30
    assert result["days_remaining"] == 15
    assert result["pct_used"] == pytest.approx(41.67, rel=0.01)
    assert result["projected_month_cost"] == pytest.approx(2500.0)
    assert result["remaining_kes"] == pytest.approx(1750.0)
    assert result["daily_allowance_remaining"] == pytest.approx(116.67, rel=0.01)
    assert result["on_track"] is True
    assert result["projected_overage"] == 0.0
    assert result["est_exhaustion_date"] is not None


@pytest.mark.unit
def test_over_pace_projection():
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    result = compute_budget_cap(
        now=now,
        month_to_date_kwh=80.0,
        tariff_kwh_cost=25.0,
        monthly_budget_kes=3000.0,
    )
    # 2000 spent in 10 days → projected 6000
    assert result["month_to_date_cost"] == pytest.approx(2000.0)
    assert result["on_track"] is False
    assert result["projected_overage"] == pytest.approx(3000.0)


@pytest.mark.unit
def test_no_usage_no_exhaustion_date():
    now = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    result = compute_budget_cap(
        now=now,
        month_to_date_kwh=0.0,
        tariff_kwh_cost=25.0,
        monthly_budget_kes=3000.0,
    )
    assert result["month_to_date_cost"] == 0.0
    assert result["est_exhaustion_date"] is None
