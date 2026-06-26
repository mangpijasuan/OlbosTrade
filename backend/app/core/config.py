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

    # ── Active broker ─────────────────────────────────────────────────────
    broker: str = Field(default="ibkr", description="Active broker: ibkr")

    # ── IBKR ──────────────────────────────────────────────────────────────
    ibkr_host: str = Field(default="127.0.0.1")
    ibkr_port: int = Field(default=7497)
    ibkr_client_id: int = Field(default=1)
    ibkr_trading_mode: str = Field(default="paper")

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://options_user:options_pass@localhost:5432/options_db"
    )

    # ── Trading Rules ─────────────────────────────────────────────────────
    starting_capital: float = Field(default=25000.0)
    max_daily_loss_pct: float = Field(default=0.02)
    max_weekly_loss_pct: float = Field(default=0.05)
    max_monthly_loss_pct: float = Field(default=0.10)
    max_concurrent_positions: int = Field(default=5)
    max_trades_per_day: int = Field(default=6)
    max_consecutive_losses: int = Field(default=3)
    cooling_off_hours: int = Field(default=24)
    capital_preservation_threshold: float = Field(default=0.85)

    # ── Equity signal settings ────────────────────────────────────────────
    equity_watchlist: str = Field(
        default="AAPL,NVDA,MSFT,META,AMZN,GOOGL,AMD,TSLA,SPY,QQQ,JPM,V,MA"
    )
    equity_signal_interval_minutes: int = Field(default=15)
    equity_min_confidence: float = Field(default=0.62)
    # Paper mode uses a lower confidence threshold to accumulate trade data
    # for ML model training. Set equal to equity_min_confidence for live.
    equity_min_confidence_paper: float = Field(default=0.45)
    equity_min_risk_reward: float = Field(default=1.80)
    earnings_gate_days: int = Field(default=3)
    max_equity_positions: int = Field(default=5)
    max_options_positions: int = Field(default=5)

    @property
    def effective_equity_min_confidence(self) -> float:
        """Use lower threshold in paper mode to build training data faster."""
        if self.ibkr_trading_mode == "paper":
            return self.equity_min_confidence_paper
        return self.equity_min_confidence

    # ── Order execution ───────────────────────────────────────────────────
    # When True, orders are only submitted during US regular trading hours
    # (09:30–16:00 ET, Mon–Fri, excluding holidays). The app still runs 24/7 —
    # only order submission pauses outside RTH and resumes automatically at the
    # open. Set False to allow order attempts at any time (not recommended:
    # options don't trade after hours and equity fills are poor).
    market_hours_only: bool = Field(default=True)
    # Spread limit price multiplier applied to estimated net credit.
    # 1.0 = submit at mid (best fill rate). 0.90 = accept 10% less credit.
    # Lower values → more fills, lower credit received.
    limit_price_aggression: float = Field(default=1.0)
    # Seconds to wait for a fill before cancelling and retrying at a lower price.
    fill_timeout_seconds: int = Field(default=60)
    # How much to lower the limit price (in dollars) on each retry.
    retry_price_step: float = Field(default=0.05)
    # Maximum number of cancel-and-retry attempts per order.
    max_order_retries: int = Field(default=2)

    # ── AI Signal Scorer ──────────────────────────────────────────────────
    signal_score_threshold: float = Field(default=0.65)
    signal_score_preservation_mode: float = Field(default=0.80)
    model_path: str = Field(default="ml/model_registry/signal_scorer_v1.pkl")
    retrain_schedule: str = Field(default="monthly")

    # ── Security ─────────────────────────────────────────────────────────
    secret_key: str = Field(default="", description="API secret key for admin endpoints")

    # ── AI Research Assistant (provider-agnostic; Gemini default, free tier) ──
    llm_provider: str = Field(default="gemini", description="gemini | anthropic | auto")
    gemini_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    llm_model: str = Field(default="", description="Override model id; blank = provider default")

    # ── Alerts ────────────────────────────────────────────────────────────
    sendgrid_api_key: str = Field(default="")
    alert_email: str = Field(default="")
    log_level: str = Field(default="INFO")

    def get_equity_watchlist(self) -> list[str]:
        """Parse comma-separated watchlist into a list."""
        return [t.strip().upper() for t in self.equity_watchlist.split(",") if t.strip()]


settings = Settings()
