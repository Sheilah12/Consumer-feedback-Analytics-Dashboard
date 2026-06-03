"""Rule-based energy-saving tips from aggregated consumption patterns."""

from __future__ import annotations

from typing import Any, Optional


def generate_energy_tips(
    *,
    overnight_avg_power: float,
    evening_peak_kwh: float,
    total_week_kwh: float,
    pct_change_week: Optional[float],
    budget_on_track: Optional[bool],
    projected_overage_kes: float,
    daily_reduction_kwh: float,
) -> list[dict[str, str]]:
    """Return short actionable tips with severity info | warn | alert."""
    tips: list[dict[str, str]] = []

    if overnight_avg_power >= 80:
        tips.append(
            {
                "text": "Phantom/standby load detected overnight — unplug idle devices or use smart strips.",
                "severity": "warn",
            }
        )
    elif overnight_avg_power >= 40:
        tips.append(
            {
                "text": "Moderate overnight baseline — check TVs, routers, and chargers left on standby.",
                "severity": "info",
            }
        )

    if total_week_kwh > 0 and evening_peak_kwh / total_week_kwh >= 0.35:
        tips.append(
            {
                "text": "Peak usage concentrated 18:00–22:00 — shift heavy appliances off the evening peak.",
                "severity": "warn",
            }
        )

    if pct_change_week is not None and pct_change_week > 10:
        tips.append(
            {
                "text": f"Usage up {pct_change_week:.0f}% vs last week — review recent appliance changes.",
                "severity": "warn" if pct_change_week > 20 else "info",
            }
        )
    elif pct_change_week is not None and pct_change_week < -10:
        tips.append(
            {
                "text": f"Usage down {abs(pct_change_week):.0f}% vs last week — good progress.",
                "severity": "info",
            }
        )

    if budget_on_track is False and projected_overage_kes > 0:
        reduction = max(0.1, daily_reduction_kwh)
        tips.append(
            {
                "text": (
                    f"On pace to exceed your budget — reduce by about {reduction:.1f} kWh/day "
                    "to stay under cap."
                ),
                "severity": "alert",
            }
        )

    if not tips:
        tips.append(
            {
                "text": "No major anomalies detected — keep monitoring weekly trends.",
                "severity": "info",
            }
        )

    return tips[:5]
