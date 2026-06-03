"""Pydantic models for API request/response validation."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class Reading(BaseModel):
    """Internal model — differential_current stored in mA; energy_kwh is cumulative."""

    timestamp: datetime
    voltage: float
    current_in: float
    current_out: float
    differential_current: float = Field(..., description="|I_in - I_out| in mA")
    real_power: float
    energy_kwh: float = Field(..., description="Cumulative meter reading (kWh)")
    energy_kwh_interval: float = 0.0
    alert_triggered: bool = False
    hardware_alert: bool = False


class ReadingCreate(BaseModel):
    voltage: float
    current_in: float
    current_out: float
    differential_ma: float
    real_power: float
    energy_kwh_cumulative: float
    energy_kwh_interval: float
    alert_triggered: bool = False


class WebhookPayload(BaseModel):
    voltage: float
    current_in: float
    current_out: float
    real_power: float
    energy_kwh_cumulative: float
    hardware_alert: bool = False
    differential_ma: Optional[float] = None
    ts: Optional[datetime] = None


class Alert(BaseModel):
    id: Optional[int] = None
    timestamp: datetime
    differential_ma: float
    message: str
    acknowledged: bool = False
    cleared_at: Optional[datetime] = None


class AlertAck(BaseModel):
    id: int
    acknowledged: bool = True


class PaginatedReadings(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class PaginatedAlerts(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class HourlyBucket(BaseModel):
    hour: str
    day: str
    hour_of_day: int
    energy_kwh: float
    avg_voltage: float
    avg_current_in: float
    avg_current_out: float
    avg_differential_current: float
    avg_real_power: float
    max_real_power: float
    sample_count: int


class DailyBucket(BaseModel):
    day: str
    energy_kwh: float
    avg_power: float
    peak_current: float
    sample_count: int


class StatsSummary(BaseModel):
    today_kwh: float
    month_kwh: float
    month_cost_kes: float
    alert_count_today: int
    uptime_pct: float


class ConfigUpdate(BaseModel):
    alert_threshold_ma: Optional[float] = Field(None, ge=0)
    tariff_kwh_cost: Optional[float] = Field(None, ge=0)


class ConfigResponse(BaseModel):
    alert_threshold_ma: float
    tariff_kwh_cost: float
    currency: str = "KES"
    token_set: bool = False


class HealthResponse(BaseModel):
    status: str
    db: str
    blynk: str
    last_ingest_ts: Optional[str] = None
    db_size_bytes: Optional[int] = None
    demo_mode: bool = False


class SettingsUpdate(BaseModel):
    blynk_token: Optional[str] = None
    tariff_kwh_cost: Optional[float] = Field(None, ge=0)
    alert_threshold_ma: Optional[float] = Field(None, ge=0)


class SettingsResponse(BaseModel):
    blynk_token_set: bool
    tariff_kwh_cost: float
    alert_threshold_ma: float
    use_dummy_data: bool
    demo_mode: bool
    currency: str = "KES"


class BudgetEstimate(BaseModel):
    energy_kwh: float
    tariff_kwh_cost: float
    estimated_cost_kes: float
    cap_kwh: Optional[float] = None
    cap_cost_kes: Optional[float] = None
    over_cap: bool = False
    currency: str = "KES"
