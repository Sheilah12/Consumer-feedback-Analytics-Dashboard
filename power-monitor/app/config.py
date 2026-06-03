"""Application settings loaded from environment (Vercel project settings / .env)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""

    blynk_token: str = ""
    blynk_server: str = "https://blynk.cloud"

    ingest_secret: str = ""
    admin_token: str = ""
    cron_secret: str = ""

    alert_threshold_ma: float = 100.0
    isolation_threshold_ma: float = 300.0
    consecutive_samples: int = 2
    tariff_kwh_cost: float = 25.0
    monthly_budget_kes: float = 3000.0
    currency: str = "KES"
    retention_days: int = 30

    debug: bool = False

    @property
    def blynk_base_url(self) -> str:
        base = self.blynk_server.rstrip("/")
        if base.endswith("/external/api"):
            return base
        return f"{base}/external/api"

    @property
    def blynk_pin_keys(self) -> list[str]:
        return ["v0", "v1", "v2", "v3", "v4", "v5"]

    @property
    def has_database(self) -> bool:
        return bool(self.database_url.strip())


settings = Settings()
