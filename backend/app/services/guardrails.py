"""
Psychological Guardrail Engine — the most important module in the platform.
ALL trading decisions must pass through GuardrailEngine.check_all().
No trade can execute if trading_allowed is False.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GuardrailStatus:
    """Result of a full guardrail check. trading_allowed must be True to place any trade."""
    trading_allowed: bool
    trading_mode: str           # "normal" | "capital_preservation" | "suspended"
    reason: Optional[str]       # Human-readable reason if blocked
    cooling_off_until: Optional[datetime]
    suspended_until: Optional[datetime]
    daily_loss_pct: float
    weekly_loss_pct: float
    monthly_loss_pct: float
    consecutive_losses: int
    trades_today: int
    capital_pct_remaining: float  # 1.0 = full capital, 0.85 = 85% remaining
    flags: list[str] = field(default_factory=list)


@dataclass
class PortfolioState:
    """Snapshot of portfolio state passed into guardrail checks."""
    current_value: float
    starting_capital: float
    daily_pnl: float
    weekly_pnl: float
    monthly_pnl: float
    consecutive_losses: int
    trades_today: int
    cooling_off_until: Optional[datetime] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GuardrailEngine:
    """
    Enforces all psychological and risk-based trading limits.
    Rules are loaded from settings (never hardcoded here).

    Hierarchy of checks (stops at first violation):
    1. Cooling off period active
    2. Daily loss limit
    3. Weekly loss limit
    4. Monthly loss limit
    5. Consecutive loss limit
    6. Daily trade cap
    7. Capital preservation mode check
    """

    def __init__(self) -> None:
        self.max_daily_loss_pct = settings.max_daily_loss_pct
        self.max_weekly_loss_pct = settings.max_weekly_loss_pct
        self.max_monthly_loss_pct = settings.max_monthly_loss_pct
        self.cooling_off_hours = settings.cooling_off_hours
        self.max_trades_per_day = settings.max_trades_per_day
        self.max_consecutive_losses = settings.max_consecutive_losses
        self.preservation_threshold = settings.capital_preservation_threshold

    def check_all(self, portfolio: PortfolioState) -> GuardrailStatus:
        """
        Run all guardrail checks against current portfolio state.
        Returns GuardrailStatus — caller must check trading_allowed before placing any trade.
        """
        flags: list[str] = []
        base = portfolio.starting_capital if portfolio.starting_capital > 0 else 1.0
        capital_pct = portfolio.current_value / base

        daily_loss_pct = portfolio.daily_pnl / base
        weekly_loss_pct = portfolio.weekly_pnl / base
        monthly_loss_pct = portfolio.monthly_pnl / base

        # ── 1. Cooling off period ──────────────────────────────────────────
        if portfolio.cooling_off_until:
            now = datetime.now(timezone.utc)
            if now < portfolio.cooling_off_until:
                remaining = portfolio.cooling_off_until - now
                reason = (
                    f"Cooling off period active — {int(remaining.total_seconds() / 3600)}h remaining. "
                    f"Trading resumes at {portfolio.cooling_off_until.strftime('%Y-%m-%d %H:%M UTC')}"
                )
                logger.warning("GUARDRAIL BLOCK — cooling off: %s", reason)
                return GuardrailStatus(
                    trading_allowed=False,
                    trading_mode="suspended",
                    reason=reason,
                    cooling_off_until=portfolio.cooling_off_until,
                    suspended_until=portfolio.cooling_off_until,
                    daily_loss_pct=daily_loss_pct,
                    weekly_loss_pct=weekly_loss_pct,
                    monthly_loss_pct=monthly_loss_pct,
                    consecutive_losses=portfolio.consecutive_losses,
                    trades_today=portfolio.trades_today,
                    capital_pct_remaining=capital_pct,
                    flags=["cooling_off_active"],
                )

        # ── 2. Daily loss limit ────────────────────────────────────────────
        if daily_loss_pct <= -self.max_daily_loss_pct:
            suspended_until = datetime.now(timezone.utc) + timedelta(hours=self.cooling_off_hours)
            reason = (
                f"Daily loss limit hit: {daily_loss_pct:.2%} "
                f"(limit: -{self.max_daily_loss_pct:.2%}). "
                f"Trading suspended for {self.cooling_off_hours}h."
            )
            logger.warning("GUARDRAIL BLOCK — daily loss: %s", reason)
            flags.append("daily_loss_limit")
            return GuardrailStatus(
                trading_allowed=False,
                trading_mode="suspended",
                reason=reason,
                cooling_off_until=suspended_until,
                suspended_until=suspended_until,
                daily_loss_pct=daily_loss_pct,
                weekly_loss_pct=weekly_loss_pct,
                monthly_loss_pct=monthly_loss_pct,
                consecutive_losses=portfolio.consecutive_losses,
                trades_today=portfolio.trades_today,
                capital_pct_remaining=capital_pct,
                flags=flags,
            )

        # ── 3. Weekly loss limit ───────────────────────────────────────────
        if weekly_loss_pct <= -self.max_weekly_loss_pct:
            suspended_until = datetime.now(timezone.utc) + timedelta(days=3)
            reason = (
                f"Weekly loss limit hit: {weekly_loss_pct:.2%} "
                f"(limit: -{self.max_weekly_loss_pct:.2%}). "
                f"Trading paused for 3 days."
            )
            logger.warning("GUARDRAIL BLOCK — weekly loss: %s", reason)
            flags.append("weekly_loss_limit")
            return GuardrailStatus(
                trading_allowed=False,
                trading_mode="suspended",
                reason=reason,
                cooling_off_until=suspended_until,
                suspended_until=suspended_until,
                daily_loss_pct=daily_loss_pct,
                weekly_loss_pct=weekly_loss_pct,
                monthly_loss_pct=monthly_loss_pct,
                consecutive_losses=portfolio.consecutive_losses,
                trades_today=portfolio.trades_today,
                capital_pct_remaining=capital_pct,
                flags=flags,
            )

        # ── 4. Monthly loss limit ──────────────────────────────────────────
        if monthly_loss_pct <= -self.max_monthly_loss_pct:
            suspended_until = datetime.now(timezone.utc) + timedelta(days=30)
            reason = (
                f"Monthly loss limit hit: {monthly_loss_pct:.2%} "
                f"(limit: -{self.max_monthly_loss_pct:.2%}). "
                f"Full review required. Trading suspended for 30 days."
            )
            logger.warning("GUARDRAIL BLOCK — monthly loss: %s", reason)
            flags.append("monthly_loss_limit")
            return GuardrailStatus(
                trading_allowed=False,
                trading_mode="suspended",
                reason=reason,
                cooling_off_until=suspended_until,
                suspended_until=suspended_until,
                daily_loss_pct=daily_loss_pct,
                weekly_loss_pct=weekly_loss_pct,
                monthly_loss_pct=monthly_loss_pct,
                consecutive_losses=portfolio.consecutive_losses,
                trades_today=portfolio.trades_today,
                capital_pct_remaining=capital_pct,
                flags=flags,
            )

        # ── 5. Consecutive loss limit ──────────────────────────────────────
        if portfolio.consecutive_losses >= self.max_consecutive_losses:
            suspended_until = datetime.now(timezone.utc) + timedelta(hours=48)
            reason = (
                f"{portfolio.consecutive_losses} consecutive losses "
                f"(limit: {self.max_consecutive_losses}). "
                f"Trading paused for 48 hours."
            )
            logger.warning("GUARDRAIL BLOCK — consecutive losses: %s", reason)
            flags.append("consecutive_loss_limit")
            return GuardrailStatus(
                trading_allowed=False,
                trading_mode="suspended",
                reason=reason,
                cooling_off_until=suspended_until,
                suspended_until=suspended_until,
                daily_loss_pct=daily_loss_pct,
                weekly_loss_pct=weekly_loss_pct,
                monthly_loss_pct=monthly_loss_pct,
                consecutive_losses=portfolio.consecutive_losses,
                trades_today=portfolio.trades_today,
                capital_pct_remaining=capital_pct,
                flags=flags,
            )

        # ── 6. Daily trade cap ─────────────────────────────────────────────
        if portfolio.trades_today >= self.max_trades_per_day:
            reason = (
                f"Daily trade cap reached: {portfolio.trades_today}/{self.max_trades_per_day}. "
                f"No more trades today."
            )
            logger.info("GUARDRAIL BLOCK — trade cap: %s", reason)
            flags.append("daily_trade_cap")
            return GuardrailStatus(
                trading_allowed=False,
                trading_mode="normal",
                reason=reason,
                cooling_off_until=None,
                suspended_until=None,
                daily_loss_pct=daily_loss_pct,
                weekly_loss_pct=weekly_loss_pct,
                monthly_loss_pct=monthly_loss_pct,
                consecutive_losses=portfolio.consecutive_losses,
                trades_today=portfolio.trades_today,
                capital_pct_remaining=capital_pct,
                flags=flags,
            )

        # ── 7. Capital preservation mode ──────────────────────────────────
        trading_mode = "normal"
        if capital_pct <= self.preservation_threshold:
            trading_mode = "capital_preservation"
            flags.append("capital_preservation_mode")
            logger.info(
                "Capital preservation mode active — account at %.1f%% of starting capital",
                capital_pct * 100,
            )

        logger.debug(
            "Guardrail check passed — mode=%s capital=%.1f%% daily=%.2f%% weekly=%.2f%%",
            trading_mode, capital_pct * 100, daily_loss_pct * 100, weekly_loss_pct * 100,
        )

        return GuardrailStatus(
            trading_allowed=True,
            trading_mode=trading_mode,
            reason=None,
            cooling_off_until=None,
            suspended_until=None,
            daily_loss_pct=daily_loss_pct,
            weekly_loss_pct=weekly_loss_pct,
            monthly_loss_pct=monthly_loss_pct,
            consecutive_losses=portfolio.consecutive_losses,
            trades_today=portfolio.trades_today,
            capital_pct_remaining=capital_pct,
            flags=flags,
        )

    def is_strategy_allowed(self, strategy: str, status: GuardrailStatus) -> bool:
        """
        In capital preservation mode, only credit spreads are allowed.
        Iron Condor and Debit Spreads are suspended.
        """
        if not status.trading_allowed:
            return False
        if status.trading_mode == "capital_preservation":
            allowed = {"bull_put_spread", "bear_call_spread"}
            return strategy in allowed
        return True

    def get_signal_threshold(self, status: GuardrailStatus) -> float:
        """Return the minimum AI signal score required to trade."""
        if status.trading_mode == "capital_preservation":
            return settings.signal_score_preservation_mode
        return settings.signal_score_threshold

    def get_position_size_multiplier(self, status: GuardrailStatus) -> float:
        """In capital preservation mode, cut position size by 50%."""
        if status.trading_mode == "capital_preservation":
            return 0.50
        return 1.0
