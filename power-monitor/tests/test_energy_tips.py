"""Unit tests for energy-saving tips."""

from __future__ import annotations

import pytest

from app.energy_tips import generate_energy_tips


@pytest.mark.unit
def test_tips_overnight_baseline():
    tips = generate_energy_tips(
        overnight_avg_power=120.0,
        evening_peak_kwh=0.0,
        total_week_kwh=10.0,
        pct_change_week=0.0,
        budget_on_track=True,
        projected_overage_kes=0.0,
        daily_reduction_kwh=0.0,
    )
    assert any("overnight" in t["text"].lower() for t in tips)


@pytest.mark.unit
def test_tips_week_over_week():
    tips = generate_energy_tips(
        overnight_avg_power=10.0,
        evening_peak_kwh=1.0,
        total_week_kwh=20.0,
        pct_change_week=15.0,
        budget_on_track=True,
        projected_overage_kes=0.0,
        daily_reduction_kwh=0.0,
    )
    assert any("15%" in t["text"] for t in tips)


@pytest.mark.unit
def test_tips_budget_overage():
    tips = generate_energy_tips(
        overnight_avg_power=10.0,
        evening_peak_kwh=1.0,
        total_week_kwh=20.0,
        pct_change_week=0.0,
        budget_on_track=False,
        projected_overage_kes=500.0,
        daily_reduction_kwh=2.5,
    )
    assert any("budget" in t["text"].lower() for t in tips)
    assert any(t["severity"] == "alert" for t in tips)
