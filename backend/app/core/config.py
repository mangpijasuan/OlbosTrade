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
    broker: str = Field(default="ibkr", description="Active broker: ibkr | alpaca")

    # ── IBKR ──────────────────────────────────────────────────────────────
    ibkr_host: str = Field(default="127.0.0.1")
    ibkr_port: int = Field(default=7497)
    ibkr_client_id: int = Field(default=1)
    ibkr_trading_mode: str = Field(default="paper")

    # ── Alpaca ────────────────────────────────────────────────────────────
    alpaca_api_key: str = Field(default="")
    alpaca_secret_key: str = Field(default="")
    alpaca_base_url: str = Field(default="https://paper-api.alpaca.markets")

    # ── Legacy Tradier (removed — use IBKR or Alpaca) ─────────────────────

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
    max_trades_per_day: int = Field(default=6)
    max_consecutive_losses: int = Field(default=3)
    cooling_off_hours: int = Field(default=24)
    capital_preservation_threshold: float = Field(default=0.85)
    max_options_positions: int = Field(default=5)
    options_exit_monitor_interval_seconds: int = Field(default=60)

    # ── Order execution ───────────────────────────────────────────────────
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

    # ── Options Flow (Options Intelligence module) ────────────────────────
    # Master switch. Streaming real options flow requires a LIVE IBKR OPRA
    # market-data subscription (reqTickByTickData does not work on delayed
    # data). This app currently runs IBKR on delayed-frozen data, so the
    # default is OFF — the module wires up cleanly and activates the moment a
    # live subscription is available and this flag is set to true.
    options_flow_enabled: bool = Field(default=False)
    # Emit synthetic ticks so the full pipeline (ingest → sweep → DB → WS →
    # UI) can be exercised without a live data feed. For demos / testing only.
    options_flow_demo_mode: bool = Field(default=False)
    options_flow_watchlist: str = Field(default="SPY,QQQ,IWM,AAPL,TSLA,NVDA")
    options_flow_max_dte: int = Field(default=60)
    # Max number of option contracts to subscribe to concurrently. IBKR caps
    # market-data lines at 100; tick-by-tick + a quote line are used per
    # contract, so stay well under the cap.
    options_flow_max_contracts: int = Field(default=40)
    options_flow_sweep_window_ms: int = Field(default=500)
    options_flow_block_min_size: int = Field(default=500)
    options_flow_large_sweep_premium: float = Field(default=500_000.0)
    options_flow_channel: str = Field(default="options_flow_live")
    # Data retention: rows older than this are archived to JSONL and deleted.
    options_flow_retention_days: int = Field(default=90)
    options_flow_archive_dir: str = Field(default="/data/archive")

    def get_options_flow_watchlist(self) -> list[str]:
        """Parse the comma-separated options-flow watchlist into a list."""
        return [
            t.strip().upper()
            for t in self.options_flow_watchlist.split(",")
            if t.strip()
        ]

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
