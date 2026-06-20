"""
Trading Mode System — Conservative, Balanced, Aggressive, Scalper.

Each mode is a complete configuration profile that overrides strategy
parameters, position sizing, DTE targets, and signal thresholds.

IMMUTABLE GUARDRAILS (never changed by any mode):
  - Daily/weekly/monthly loss limits
  - Kill switch
  - Position reconciliation
  - Consecutive loss cooling off
  - Capital preservation threshold

WHAT MODES CONTROL:
  - DTE range (target days to expiration)
  - Profit target % (when to close winners)
  - Stop loss multiplier (when to close losers)
  - Signal score threshold (how selective the AI is)
  - Max trades per day
  - Position size (% of portfolio per trade)
  - Which strategies are allowed
  - Whether human monitoring is required
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TradingModeType(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED     = "balanced"
    AGGRESSIVE   = "aggressive"
    SCALPER      = "scalper"


@dataclass(frozen=True)
class TradingModeConfig:
    """
    Complete configuration for a single trading mode.
    Frozen — cannot be modified after creation.
    All modes share the same immutable financial guardrails.
    """
    mode:                  TradingModeType
    display_name:          str
    description:           str

    # ── DTE ────────────────────────────────────────────────────────────────
    dte_min:               int
    dte_target:            int
    dte_max:               int
    dte_exit:              int         # Close position at this DTE regardless

    # ── Exit rules ─────────────────────────────────────────────────────────
    profit_target_pct:     float       # Close when this % of max profit reached
    stop_loss_multiplier:  float       # Close when loss = this × credit received

    # ── Entry filters ──────────────────────────────────────────────────────
    signal_threshold:      float       # Min AI score to enter
    min_iv_rank:           float       # Min IV rank to enter
    min_credit_to_width:   float       # Min credit/width ratio

    # ── Position sizing ────────────────────────────────────────────────────
    risk_per_trade_pct:    float       # % of portfolio risked per trade
    max_trades_per_day:    int
    max_concurrent:        int

    # ── Strategy permissions ────────────────────────────────────────────────
    bull_put_allowed:      bool
    bear_call_allowed:     bool
    iron_condor_allowed:   bool
    debit_spread_allowed:  bool

    # ── Monitoring requirement ─────────────────────────────────────────────
    requires_monitoring:   bool        # If True, warn user to watch screen
    monitoring_warning:    str

    # ── Color for UI ──────────────────────────────────────────────────────
    ui_color:              str         # green / blue / orange / red
    ui_icon:               str


# ── Mode definitions ───────────────────────────────────────────────────────────

TRADING_MODES: dict[TradingModeType, TradingModeConfig] = {

    TradingModeType.CONSERVATIVE: TradingModeConfig(
        mode=TradingModeType.CONSERVATIVE,
        display_name="Conservative",
        description=(
            "Capital preservation first. Fewer trades, wider DTE, "
            "higher signal requirements. Best for volatile markets "
            "or when starting out."
        ),
        # DTE — widest range, most forgiving
        dte_min=30, dte_target=45, dte_max=60, dte_exit=21,
        # Exit rules — patient
        profit_target_pct=0.50,
        stop_loss_multiplier=2.0,
        # Entry — very selective
        signal_threshold=0.72,
        min_iv_rank=35.0,
        min_credit_to_width=0.25,
        # Sizing — smallest risk
        risk_per_trade_pct=0.01,   # 1% per trade
        max_trades_per_day=1,
        max_concurrent=3,
        # Strategies — credit only, no debit
        bull_put_allowed=True,
        bear_call_allowed=True,
        iron_condor_allowed=True,
        debit_spread_allowed=False,
        # Monitoring — fully automated
        requires_monitoring=False,
        monitoring_warning="",
        ui_color="green",
        ui_icon="shield",
    ),

    TradingModeType.BALANCED: TradingModeConfig(
        mode=TradingModeType.BALANCED,
        display_name="Balanced",
        description=(
            "The default OlbosQuant mode. Proven 30–35 DTE sweet spot "
            "for the volatility risk premium. Fully automated. "
            "Recommended for most traders."
        ),
        # DTE — sweet spot
        dte_min=15, dte_target=22, dte_max=30, dte_exit=10,
        # Exit rules — standard
        profit_target_pct=0.50,
        stop_loss_multiplier=2.0,
        # Entry — standard
        signal_threshold=0.65,
        min_iv_rank=30.0,
        min_credit_to_width=0.20,
        # Sizing — standard
        risk_per_trade_pct=0.02,   # 2% per trade
        max_trades_per_day=3,
        max_concurrent=5,
        # Strategies — all allowed
        bull_put_allowed=True,
        bear_call_allowed=True,
        iron_condor_allowed=True,
        debit_spread_allowed=True,
        # Monitoring — fully automated
        requires_monitoring=False,
        monitoring_warning="",
        ui_color="blue",
        ui_icon="activity",
    ),

    TradingModeType.AGGRESSIVE: TradingModeConfig(
        mode=TradingModeType.AGGRESSIVE,
        display_name="Aggressive",
        description=(
            "Shorter DTE (7–15 days) for faster premium collection. "
            "Higher gamma risk — losses can accumulate quickly. "
            "Take profits faster, cut losses faster. "
            "Check the system twice daily."
        ),
        # DTE — short but not 0DTE danger zone
        dte_min=3, dte_target=9, dte_max=15, dte_exit=2,
        # Exit rules — faster on both sides
        profit_target_pct=0.35,    # Take 35% profit — don't be greedy
        stop_loss_multiplier=1.5,  # Cut at 1.5x — faster than balanced
        # Entry — slightly looser (more trades)
        signal_threshold=0.60,
        min_iv_rank=30.0,
        min_credit_to_width=0.22,
        # Sizing — slightly larger but gamma demands caution
        risk_per_trade_pct=0.025,  # 2.5% per trade
        max_trades_per_day=3,
        max_concurrent=4,           # Fewer concurrent — gamma compounds
        # Strategies — credit spreads only (no condors at short DTE)
        bull_put_allowed=True,
        bear_call_allowed=True,
        iron_condor_allowed=False,  # Too dangerous at 7-15 DTE
        debit_spread_allowed=False,
        # Monitoring — recommended twice daily
        requires_monitoring=False,  # Still automatable
        monitoring_warning=(
            "Aggressive mode uses 7–15 DTE options. Gamma risk is elevated. "
            "A single large SPY move can cause significant losses quickly at 7–15 DTE. "
            "Check positions morning and afternoon during market hours."
        ),
        ui_color="orange",
        ui_icon="zap",
    ),

    TradingModeType.SCALPER: TradingModeConfig(
        mode=TradingModeType.SCALPER,
        display_name="Scalper (0–3 DTE)",
        description=(
            "Zero to 3 DTE options. Maximum theta decay but maximum "
            "gamma risk. A single 1% SPY move can cause max loss. "
            "REQUIRES active monitoring during market hours. "
            "Not suitable for passive automated trading."
        ),
        # DTE — extreme short
        dte_min=0, dte_target=1, dte_max=3, dte_exit=0,
        # Exit rules — lightning fast
        profit_target_pct=0.25,    # 25% profit — get out quickly
        stop_loss_multiplier=1.0,  # Stop at 1x credit — immediate
        # Entry — highest threshold (compensates for thin edge)
        signal_threshold=0.70,
        min_iv_rank=35.0,
        min_credit_to_width=0.30,  # Higher credit requirement
        # Sizing — smallest (gamma can cause instant max loss)
        risk_per_trade_pct=0.005,  # 0.5% per trade only
        max_trades_per_day=3,
        max_concurrent=2,           # Never hold more than 2 at once
        # Strategies — puts only (directional is too dangerous)
        bull_put_allowed=True,
        bear_call_allowed=True,
        iron_condor_allowed=False,
        debit_spread_allowed=False,
        # Monitoring — MANDATORY
        requires_monitoring=True,
        monitoring_warning=(
            "⚠️ SCALPER MODE REQUIRES ACTIVE MONITORING.\n\n"
            "0–3 DTE options can go from full profit to max loss in under "
            "60 minutes on a normal SPY move. The automated stop loss "
            "will attempt to protect you, but fill quality degrades "
            "rapidly during fast markets.\n\n"
            "DO NOT run Scalper mode if you cannot watch the market "
            "between 9:30am and 4:00pm ET. Use Balanced or Conservative "
            "mode for passive automated trading."
        ),
        ui_color="red",
        ui_icon="alert-triangle",
    ),
}


@dataclass
class TradingModeState:
    """
    Current active trading mode with metadata.
    Persisted to DB so it survives restarts.
    """
    active_mode:    TradingModeType
    config:         TradingModeConfig
    activated_at:   datetime
    activated_by:   str                 # "user" | "auto_capital_preservation"
    previous_mode:  Optional[TradingModeType] = None
    override_reason: Optional[str] = None


class TradingModeManager:
    """
    Manages the active trading mode.
    Single source of truth for all mode-related configuration.

    Integration points:
      - paper_trader.py reads mode config for DTE and sizing
      - strategy_engine.py reads profit_target and stop_loss
      - guardrails.py reads signal_threshold and max_trades
      - frontend reads mode for display and user switching
    """

    _PERSIST_PATH = "/tmp/olbosquant_trading_mode.json"

    def __init__(self) -> None:
        # Try to restore previously persisted mode
        persisted_mode = TradingModeType.BALANCED
        try:
            import json, os
            if os.path.exists(self._PERSIST_PATH):
                data = json.loads(open(self._PERSIST_PATH).read())
                persisted_mode = TradingModeType(data.get("mode", "balanced"))
        except Exception:
            pass

        self._current = TradingModeState(
            active_mode=persisted_mode,
            config=TRADING_MODES[persisted_mode],
            activated_at=datetime.now(timezone.utc),
            activated_by="restored",
        )
        logger.info("TradingModeManager initialized — mode: %s", persisted_mode.value.upper())

    @property
    def current(self) -> TradingModeState:
        return self._current

    @property
    def config(self) -> TradingModeConfig:
        return self._current.config

    def set_mode(
        self,
        mode: TradingModeType,
        activated_by: str = "user",
        override_reason: Optional[str] = None,
    ) -> TradingModeState:
        """
        Switch to a new trading mode.

        For Scalper mode: logs a critical warning.
        Mode changes take effect on the NEXT signal cycle —
        never mid-trade.

        Returns the new TradingModeState.
        """
        previous = self._current.active_mode
        new_config = TRADING_MODES[mode]

        # Hard warning for Scalper mode
        if mode == TradingModeType.SCALPER:
            logger.warning(
                "SCALPER MODE ACTIVATED by %s. "
                "0-3 DTE requires active human monitoring. "
                "Automated stops are in place but fill quality "
                "degrades during fast markets.",
                activated_by,
            )

        self._current = TradingModeState(
            active_mode=mode,
            config=new_config,
            activated_at=datetime.now(timezone.utc),
            activated_by=activated_by,
            previous_mode=previous,
            override_reason=override_reason,
        )

        logger.info(
            "Trading mode changed: %s → %s (by %s)",
            previous.value, mode.value, activated_by,
        )
        # Persist mode so it survives backend restarts
        try:
            import json
            with open(self._PERSIST_PATH, "w") as f:
                json.dump({"mode": mode.value}, f)
        except Exception as e:
            logger.warning("Could not persist trading mode: %s", e)
        return self._current

    def auto_downgrade(self, reason: str) -> TradingModeState:
        """
        Automatically downgrade to Conservative mode.
        Called by capital preservation logic when account
        drops below threshold.

        This is the only automatic mode change — always
        downgrade, never auto-upgrade.
        """
        if self._current.active_mode == TradingModeType.CONSERVATIVE:
            return self._current  # Already conservative

        logger.warning(
            "AUTO-DOWNGRADE to Conservative: %s "
            "(was: %s)",
            reason, self._current.active_mode.value,
        )
        return self.set_mode(
            TradingModeType.CONSERVATIVE,
            activated_by="auto_capital_preservation",
            override_reason=reason,
        )

    def get_dte_target_for_chain(self) -> str:
        """
        Returns the target expiry date string for chain fetching.
        Format: YYYY-MM-DD
        """
        from datetime import date, timedelta
        target = date.today() + timedelta(days=self.config.dte_target)
        return target.strftime("%Y-%m-%d")

    def summary(self) -> dict:
        """Human-readable summary for API and logging."""
        c = self.config
        return {
            "mode":                c.mode.value,
            "display_name":        c.display_name,
            "description":         c.description,
            "dte_range":           f"{c.dte_min}–{c.dte_max} days",
            "dte_target":          c.dte_target,
            "profit_target":       f"{c.profit_target_pct:.0%}",
            "stop_loss":           f"{c.stop_loss_multiplier}x credit",
            "signal_threshold":    c.signal_threshold,
            "risk_per_trade":      f"{c.risk_per_trade_pct:.1%}",
            "max_trades_per_day":  c.max_trades_per_day,
            "max_concurrent":      c.max_concurrent,
            "strategies_allowed":  {
                "bull_put_spread":      c.bull_put_allowed,
                "bear_call_spread":     c.bear_call_allowed,
                "iron_condor":          c.iron_condor_allowed,
                "bull_call_debit":      c.debit_spread_allowed,
            },
            "requires_monitoring": c.requires_monitoring,
            "monitoring_warning":  c.monitoring_warning,
            "ui_color":            c.ui_color,
            "activated_at":        self._current.activated_at.isoformat(),
            "activated_by":        self._current.activated_by,
        }


# ── Runtime helpers (used by options engine + trade desk) ─────────────────────

_STRATEGY_PERMISSION_KEYS: dict[str, str] = {
    "bull_put_spread":        "bull_put_allowed",
    "bear_call_spread":       "bear_call_allowed",
    "iron_condor":            "iron_condor_allowed",
    "bull_call_debit_spread": "debit_spread_allowed",
}


def is_strategy_allowed_by_mode(strategy_name: str) -> bool:
    """Return True if the active trading mode permits this strategy."""
    key = _STRATEGY_PERMISSION_KEYS.get(strategy_name)
    if key is None:
        return True
    return bool(getattr(trading_mode_manager.config, key, True))


def select_expiry_within_bounds(
    dte_target: int,
    dte_min: int,
    dte_max: int,
    *,
    prefer_friday: bool = True,
) -> tuple[Optional["date"], Optional[int]]:
    """
    Pick an expiration date whose DTE falls within [dte_min, dte_max],
    closest to dte_target.

    For short-DTE modes (dte_max <= 7) any weekday is allowed (including 0DTE).
    For longer holds, Fridays are preferred when available.
    """
    from datetime import date, timedelta

    today = date.today()
    best_date: Optional[date] = None
    best_diff = float("inf")

    def _consider(candidate: date) -> None:
        nonlocal best_date, best_diff
        offset = (candidate - today).days
        if offset < dte_min or offset > dte_max:
            return
        diff = abs(offset - dte_target)
        if diff < best_diff:
            best_diff = diff
            best_date = candidate

    use_fridays_only = prefer_friday and dte_max > 7
    for offset in range(dte_min, dte_max + 1):
        candidate = today + timedelta(days=offset)
        if use_fridays_only and candidate.weekday() != 4:
            continue
        _consider(candidate)

    if best_date is None:
        for offset in range(dte_min, dte_max + 1):
            _consider(today + timedelta(days=offset))

    if best_date is None:
        return None, None
    return best_date, (best_date - today).days


def get_effective_signal_threshold(guardrail_risk_state: str) -> float:
    """
    Minimum AI score for the active trading mode.
    Capital preservation raises the floor.
    """
    from app.core.config import settings

    base = trading_mode_manager.config.signal_threshold
    if guardrail_risk_state == "capital_preservation":
        return max(base, settings.signal_score_preservation_mode)
    return base


def get_mode_trade_limits() -> tuple[int, int]:
    """Return (max_trades_per_day, max_concurrent) from active trading mode."""
    c = trading_mode_manager.config
    return c.max_trades_per_day, c.max_concurrent


# ── Singleton ──────────────────────────────────────────────────────────────────
trading_mode_manager = TradingModeManager()
