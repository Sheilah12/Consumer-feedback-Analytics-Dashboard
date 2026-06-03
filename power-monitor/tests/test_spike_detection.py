"""Unit tests for spike detection."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.spike_detection import compute_baseline_stats, detect_spikes


@pytest.mark.unit
def test_baseline_stats():
    mean, std = compute_baseline_stats([100.0, 200.0, 300.0])
    assert mean == 200.0
    assert std > 0


@pytest.mark.unit
def test_detect_spike_by_stdev():
    recent = [
        {
            "ts": datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
            "real_power": 500.0,
            "hour_of_day": 12,
        }
    ]
    spikes = detect_spikes(
        recent,
        baseline_mean=100.0,
        baseline_std=50.0,
        hod_avg={12: 120.0},
    )
    assert len(spikes) == 1
    assert spikes[0]["real_power"] == 500.0
    assert "stdev" in spikes[0]["reason"]


@pytest.mark.unit
def test_detect_spike_by_hour_of_day():
    recent = [
        {
            "ts": datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc),
            "real_power": 300.0,
            "hour_of_day": 18,
        }
    ]
    spikes = detect_spikes(
        recent,
        baseline_mean=200.0,
        baseline_std=80.0,
        hod_avg={18: 100.0},
    )
    assert len(spikes) == 1
    assert "hour_of_day" in spikes[0]["reason"]
