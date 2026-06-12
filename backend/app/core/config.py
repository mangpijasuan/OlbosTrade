"""
Application configuration loaded from environment variables.
All runtime settings must come through this module — no hardcoded values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Broker ────────────────────────────────────────────────────────────
    broker: str = Field(default="ibkr", description="Active broker: ibkr | tradier")
    ibkr_host: str = Field(default="127.0.0.1")
    ibkr_port: int = Field(default=7497)
    ibkr_client_id: int = Field(default=1)
    tradier_api_key: str = Field(default="")
    tradier_sandbox: bool = Field(default=True)

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://options_user:options_pass@localhost:5432/options_db"
    )
    redis_url: str = Field(default="redis://localhost:6379")

    # ── Trading Rules ─────────────────────────────────────────────────────
    starting_capital: float = Field(default=25000.0)
    max_daily_loss_pct: float = Field(default=0.02)
    max_weekly_loss_pct: float = Field(default=0.05)
    max_monthly_loss_pct: float = Field(default=0.10)
    max_concurrent_positions: int = Field(default=5)
    max_trades_per_day: int = Field(default=3)
    max_consecutive_losses: int = Field(default=3)
    cooling_off_hours: int = Field(default=24)
    capital_preservation_threshold: float = Field(default=0.85)

    # ── AI Signal Scorer ──────────────────────────────────────────────────
    signal_score_threshold: float = Field(default=0.65)
    signal_score_preservation_mode: float = Field(default=0.80)
    model_path: str = Field(default="ml/model_registry/signal_scorer_v1.pkl")
    retrain_schedule: str = Field(default="monthly")

    # ── Security ─────────────────────────────────────────────────────────
    secret_key: str = Field(default="", description="API secret key for admin endpoints")

    # ── Alerts ────────────────────────────────────────────────────────────
    sendgrid_api_key: str = Field(default="")
    alert_email: str = Field(default="")
    log_level: str = Field(default="INFO")


settings = Settings()
