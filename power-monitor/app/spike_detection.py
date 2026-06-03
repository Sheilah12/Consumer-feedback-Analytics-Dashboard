"""Power spike detection — trailing stdev and hour-of-day baseline."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def detect_spikes(
    recent: list[dict[str, Any]],
    *,
    baseline_mean: float,
    baseline_std: float,
    hod_avg: dict[int, float],
    stdev_multiplier: float = 2.0,
    hod_multiplier: float = 1.5,
) -> list[dict[str, Any]]:
    """Flag readings where power exceeds mean + N·σ or ≥ M× hour-of-day average."""
    spikes: list[dict[str, Any]] = []
    threshold_stdev = baseline_mean + stdev_multiplier * baseline_std

    for row in recent:
        power = float(row["real_power"])
        ts = row["ts"]
        if isinstance(ts, datetime):
            ts_iso = ts.astimezone().isoformat().replace("+00:00", "Z")
            hod = int(row.get("hour_of_day", ts.hour))
        else:
            ts_iso = str(ts)
            hod = int(row.get("hour_of_day", 0))

        hod_baseline = hod_avg.get(hod, 0.0)
        above_stdev = baseline_std > 0 and power > threshold_stdev
        above_hod = hod_baseline > 0 and power >= hod_multiplier * hod_baseline

        if not above_stdev and not above_hod:
            continue

        reasons: list[str] = []
        if above_stdev:
            reasons.append("stdev")
        if above_hod:
            reasons.append("hour_of_day")

        refs: list[float] = []
        if above_stdev:
            refs.append(threshold_stdev)
        if above_hod:
            refs.append(hod_multiplier * hod_baseline)
        reference = max(refs) if refs else baseline_mean
        excess = power - reference
        pct_above = round((excess / reference) * 100.0, 1) if reference > 0 else 0.0
        spikes.append(
            {
                "ts": ts_iso,
                "real_power": round(power, 2),
                "baseline_mean": round(baseline_mean, 2),
                "baseline_std": round(baseline_std, 2),
                "hour_of_day_avg": round(hod_baseline, 2),
                "excess_w": round(excess, 2),
                "pct_above_normal": pct_above,
                "reason": "+".join(reasons),
            }
        )

    spikes.sort(key=lambda s: s["ts"], reverse=True)
    return spikes


def compute_baseline_stats(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, math.sqrt(variance)
