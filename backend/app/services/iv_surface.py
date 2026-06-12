"""
IV Surface & Skew Module.

Replaces the VIX-proxy IV rank with a real per-contract implied volatility surface.
Computes:
  - IV rank and IV percentile from actual options chain IV (not RV proxy)
  - Put/call skew at each expiry (25-delta put IV minus 25-delta call IV)
  - Term structure slope (front-month IV vs back-month IV)
  - Strike-level IV surface (volatility smile/skew across strikes)
  - VRP (Volatility Risk Premium) = IV rank minus realized vol

Integrates into paper_trader.run_signal_cycle() and backtester.run()
to replace the VIX-based IV rank approximation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from app.broker.broker_interface import BrokerInterface, OptionsChain
from app.services.analytics_engine import AnalyticsEngine
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
RISK_FREE_RATE       = 0.05
IV_HISTORY_LOOKBACK  = 252          # 1 year of trading days for IV rank
SKEW_DELTA_TARGET    = 0.25         # 25-delta puts/calls for skew measurement
MIN_OPEN_INTEREST    = 100          # Skip contracts with no liquidity
MIN_VOLUME           = 10


@dataclass
class SkewSnapshot:
    """
    Put/call skew for a single expiry.

    Positive skew = puts more expensive than calls (normal, fear premium).
    Negative skew = calls more expensive (unusual, squeeze/buyout pricing).
    """
    expiry:          date
    dte:             int
    put_iv_25d:      float          # IV of 25-delta put
    call_iv_25d:     float          # IV of 25-delta call
    atm_iv:          float          # ATM straddle IV
    skew:            float          # put_iv_25d - call_iv_25d
    skew_pct:        float          # skew / atm_iv (normalized)
    risk_reversal:   float          # 25d put - 25d call (same as skew here)
    butterfly:       float          # (25d put + 25d call) / 2 - ATM (convexity)


@dataclass
class TermStructure:
    """
    IV term structure across multiple expirations.

    Upward slope = backwardation is normal (near > far) during stress.
    Downward slope = contango (near < far) during calm markets.
    """
    expirations:     list[date]
    atm_ivs:         list[float]    # ATM IV per expiry
    slope:           float          # Linear regression slope (per day)
    front_iv:        float          # Nearest expiry ATM IV
    back_iv:         float          # Furthest expiry ATM IV
    in_backwardation: bool          # front > back


@dataclass
class IVSurfaceSnapshot:
    """
    Complete IV surface snapshot for a single underlying at a point in time.
    This replaces all VIX-proxy calculations in the signal cycle.
    """
    underlying:          str
    spot_price:          float
    fetched_at:          datetime

    # ── IV rank & percentile (from real chain IV, not VIX) ────────────────
    iv_rank:             float          # 0–100: where current IV sits in 1yr range
    iv_percentile:       float          # 0–100: % of days IV was below current
    atm_iv:              float          # Current ATM IV (front month)
    realized_vol_20d:    float          # 20-day historical realized vol
    vrp:                 float          # IV - RV (volatility risk premium)

    # ── Skew ──────────────────────────────────────────────────────────────
    front_skew:          Optional[SkewSnapshot]    # Nearest expiry skew
    back_skew:           Optional[SkewSnapshot]    # Second expiry skew
    skew_trend:          float          # front_skew.skew - back_skew.skew

    # ── Term structure ────────────────────────────────────────────────────
    term_structure:      Optional[TermStructure]

    # ── Quality flags ─────────────────────────────────────────────────────
    data_quality:        str            # "full" | "partial" | "fallback"
    warnings:            list[str] = field(default_factory=list)

    # ── Derived signals for strategy selection ────────────────────────────
    @property
    def is_high_iv(self) -> bool:
        """IV rank above 50 — favorable for credit spread entry."""
        return self.iv_rank > 50

    @property
    def fear_premium_elevated(self) -> bool:
        """
        Put skew is unusually high — market pricing in fear.
        Bull Put Spreads less attractive (put buyers dominating).
        Bear Call Spreads may be better risk/reward.
        """
        if self.front_skew is None:
            return False
        return self.front_skew.skew_pct > 0.20  # >20% normalized skew

    @property
    def term_structure_in_backwardation(self) -> bool:
        """
        Front IV > back IV — short-term stress elevated.
        Avoid Iron Condors; prefer single-direction spreads.
        """
        if self.term_structure is None:
            return False
        return self.term_structure.in_backwardation

    @property
    def favorable_for_iron_condor(self) -> bool:
        """
        All conditions favorable for Iron Condor:
        - High IV rank (>40)
        - Not in backwardation (calm term structure)
        - Moderate skew (not panic pricing)
        """
        return (
            self.iv_rank > 40
            and not self.term_structure_in_backwardation
            and not self.fear_premium_elevated
            and self.vrp > 0.02   # Meaningful vol premium to harvest
        )

    def strategy_recommendation(self) -> str:
        """
        Suggest which strategy is most aligned with current IV surface.
        This feeds into the regime classifier.
        """
        if self.iv_rank < 20:
            return "none"  # Too cheap to sell premium
        if self.favorable_for_iron_condor:
            return "iron_condor"
        if self.fear_premium_elevated and self.iv_rank > 35:
            return "bear_call_spread"  # Sell the expensive calls
        if self.iv_rank > 30 and not self.term_structure_in_backwardation:
            return "bull_put_spread"
        return "none"


class IVSurfaceEngine:
    """
    Builds a real IV surface from live options chain data.

    Replaces paper_trader's VIX-proxy IV rank with per-contract
    implied volatilities computed from actual bid/ask quotes.

    Usage in paper_trader:
        surface = await iv_engine.build_surface(
            symbol="SPY",
            spot_price=spy_price,
            rv_20d=rv,
        )
        iv_rank = surface.iv_rank          # use this instead of VIX proxy
        skew    = surface.front_skew.skew  # new signal
        regime  = surface.strategy_recommendation()
    """

    def __init__(
        self,
        broker: BrokerInterface,
        risk_free_rate: float = RISK_FREE_RATE,
    ) -> None:
        self.broker = broker
        self.analytics = AnalyticsEngine(risk_free_rate=risk_free_rate)
        self._iv_history: dict[str, list[tuple[date, float]]] = {}  # symbol → [(date, atm_iv)]

    async def build_surface(
        self,
        symbol: str,
        spot_price: float,
        rv_20d: float,
        target_dtes: list[int] = None,
    ) -> IVSurfaceSnapshot:
        """
        Build a complete IV surface snapshot for the given symbol.

        Fetches chains for 2-3 expirations, computes ATM IV, skew,
        term structure, and IV rank from rolling ATM IV history.

        Args:
            symbol:       Underlying ticker (e.g., "SPY")
            spot_price:   Current spot price
            rv_20d:       20-day realized volatility (decimal)
            target_dtes:  Target DTEs to fetch (default: [30, 60])

        Returns:
            IVSurfaceSnapshot with full surface data
        """
        if target_dtes is None:
            target_dtes = [30, 60]

        warnings: list[str] = []
        skew_snapshots: list[SkewSnapshot] = []
        atm_ivs_by_expiry: list[tuple[date, float]] = []

        today = datetime.now(timezone.utc).date()

        for dte_target in target_dtes:
            expiry = today + timedelta(days=dte_target)
            # Snap to end of month (standard options expiry convention)
            expiry_str = expiry.strftime("%Y-%m-%d")

            try:
                chain: OptionsChain = await self.broker.get_options_chain(
                    symbol, expiry_str
                )
                skew = self._compute_skew(chain, spot_price)
                if skew is not None:
                    skew_snapshots.append(skew)
                    atm_ivs_by_expiry.append((expiry, skew.atm_iv))
                    logger.debug(
                        "IV surface: %s %s DTE=%d ATM_IV=%.1f%% skew=%.3f",
                        symbol, expiry_str, dte_target,
                        skew.atm_iv * 100, skew.skew,
                    )
            except Exception as exc:
                warnings.append(f"Chain fetch failed for {expiry_str}: {exc}")
                logger.warning("IV surface: chain fetch failed %s %s: %s", symbol, expiry_str, exc)

        # ── ATM IV for IV rank calculation ────────────────────────────────────
        if not skew_snapshots:
            # Full fallback — no chain data available
            warnings.append("No chain data — using VIX proxy for IV rank")
            atm_iv = rv_20d * 1.15  # historical IV premium over RV
            return self._build_fallback_surface(
                symbol, spot_price, rv_20d, atm_iv, warnings
            )

        front_skew = skew_snapshots[0]
        back_skew  = skew_snapshots[1] if len(skew_snapshots) > 1 else None
        atm_iv     = front_skew.atm_iv

        # ── Update rolling IV history ─────────────────────────────────────────
        self._update_iv_history(symbol, today, atm_iv)

        # ── IV rank and percentile from real chain IV ─────────────────────────
        iv_history_values = [iv for _, iv in self._iv_history.get(symbol, [])]

        if len(iv_history_values) >= 20:
            iv_series = pd.Series(iv_history_values)
            iv_rank = self._compute_iv_rank(iv_series, atm_iv)
            iv_pct  = self._compute_iv_percentile(iv_series, atm_iv)
        else:
            # Not enough history yet — approximate from VIX
            iv_rank = min(max((atm_iv - 0.10) / 0.30 * 100, 0), 100)
            iv_pct  = iv_rank
            warnings.append(
                f"Only {len(iv_history_values)} days of IV history — "
                f"IV rank is approximate. Need 20+ days for accurate rank."
            )

        # ── VRP ───────────────────────────────────────────────────────────────
        vrp = atm_iv - rv_20d

        # ── Term structure ────────────────────────────────────────────────────
        term_structure = None
        if len(atm_ivs_by_expiry) >= 2:
            term_structure = self._compute_term_structure(atm_ivs_by_expiry)

        # ── Skew trend (front vs back) ─────────────────────────────────────────
        skew_trend = 0.0
        if front_skew and back_skew:
            skew_trend = front_skew.skew - back_skew.skew

        data_quality = "full" if not warnings else "partial"

        surface = IVSurfaceSnapshot(
            underlying=symbol,
            spot_price=spot_price,
            fetched_at=datetime.now(timezone.utc),
            iv_rank=round(iv_rank, 2),
            iv_percentile=round(iv_pct, 2),
            atm_iv=atm_iv,
            realized_vol_20d=rv_20d,
            vrp=round(vrp, 4),
            front_skew=front_skew,
            back_skew=back_skew,
            skew_trend=round(skew_trend, 4),
            term_structure=term_structure,
            data_quality=data_quality,
            warnings=warnings,
        )

        logger.info(
            "IV surface built: %s | IV_rank=%.1f IV=%.1f%% VRP=%.2f%% "
            "skew=%.3f term_slope=%+.4f quality=%s",
            symbol, iv_rank, atm_iv * 100, vrp * 100,
            front_skew.skew if front_skew else 0,
            term_structure.slope if term_structure else 0,
            data_quality,
        )
        return surface

    def _compute_skew(
        self,
        chain: OptionsChain,
        spot_price: float,
    ) -> Optional[SkewSnapshot]:
        """
        Compute put/call skew from a chain snapshot.
        Finds 25-delta put and call, ATM straddle. Returns None if insufficient data.
        """
        today = datetime.now(timezone.utc).date()
        dte = (chain.expiration - today).days
        T = max(dte / 365.0, 1.0 / (365 * 390))

        # ── Find ATM IV ───────────────────────────────────────────────────────
        atm_call = self._find_nearest_atm(chain.calls, spot_price)
        atm_put  = self._find_nearest_atm(chain.puts, spot_price)

        if atm_call is None or atm_put is None:
            return None

        try:
            atm_call_iv, _ = self.analytics.implied_vol(
                market_price=float(atm_call.bid + atm_call.ask) / 2,
                S=spot_price, K=float(atm_call.strike),
                T=T, option_type="call",
            )
            atm_put_iv, _ = self.analytics.implied_vol(
                market_price=float(atm_put.bid + atm_put.ask) / 2,
                S=spot_price, K=float(atm_put.strike),
                T=T, option_type="put",
            )
            atm_iv = (atm_call_iv + atm_put_iv) / 2
        except Exception as exc:
            logger.debug("ATM IV failed: %s", exc)
            return None

        # ── Find 25-delta put and call ────────────────────────────────────────
        put_25d  = self._find_by_delta(chain.puts,  SKEW_DELTA_TARGET, "put",  spot_price, T, atm_iv)
        call_25d = self._find_by_delta(chain.calls, SKEW_DELTA_TARGET, "call", spot_price, T, atm_iv)

        if put_25d is None or call_25d is None:
            return None

        try:
            put_iv, _ = self.analytics.implied_vol(
                market_price=float(put_25d.bid + put_25d.ask) / 2,
                S=spot_price, K=float(put_25d.strike),
                T=T, option_type="put",
            )
            call_iv, _ = self.analytics.implied_vol(
                market_price=float(call_25d.bid + call_25d.ask) / 2,
                S=spot_price, K=float(call_25d.strike),
                T=T, option_type="call",
            )
        except Exception as exc:
            logger.debug("25-delta IV failed: %s", exc)
            return None

        skew     = put_iv - call_iv
        skew_pct = skew / atm_iv if atm_iv > 0 else 0.0
        butterfly = (put_iv + call_iv) / 2 - atm_iv

        return SkewSnapshot(
            expiry=chain.expiration,
            dte=dte,
            put_iv_25d=put_iv,
            call_iv_25d=call_iv,
            atm_iv=atm_iv,
            skew=round(skew, 4),
            skew_pct=round(skew_pct, 4),
            risk_reversal=round(skew, 4),
            butterfly=round(butterfly, 4),
        )

    def _find_nearest_atm(self, contracts, spot_price: float):
        """Find the contract with strike nearest to spot price."""
        if not contracts:
            return None
        return min(
            [c for c in contracts if int(c.open_interest) >= MIN_OPEN_INTEREST],
            key=lambda c: abs(float(c.strike) - spot_price),
            default=None,
        )

    def _find_by_delta(self, contracts, target_delta: float, option_type: str,
                       S: float, T: float, sigma: float):
        """Find the contract closest to target delta."""
        best = None
        best_diff = float("inf")
        for c in contracts:
            if int(c.open_interest) < MIN_OPEN_INTEREST:
                continue
            try:
                d = self.analytics.greeks(S, float(c.strike), T, sigma, option_type)
                diff = abs(abs(d["delta"]) - target_delta)
                if diff < best_diff:
                    best_diff = diff
                    best = c
            except Exception:
                continue
        return best

    def _compute_term_structure(
        self, ivs_by_expiry: list[tuple[date, float]]
    ) -> TermStructure:
        """Compute term structure slope from ATM IV across expirations."""
        ivs_by_expiry.sort(key=lambda x: x[0])
        dates_arr = np.array([(d - ivs_by_expiry[0][0]).days for d, _ in ivs_by_expiry], dtype=float)
        ivs_arr   = np.array([iv for _, iv in ivs_by_expiry])

        slope = float(np.polyfit(dates_arr, ivs_arr, 1)[0]) if len(dates_arr) >= 2 else 0.0
        front_iv = ivs_arr[0]
        back_iv  = ivs_arr[-1]

        return TermStructure(
            expirations=[d for d, _ in ivs_by_expiry],
            atm_ivs=list(ivs_arr),
            slope=round(slope, 6),
            front_iv=front_iv,
            back_iv=back_iv,
            in_backwardation=front_iv > back_iv,
        )

    def _update_iv_history(self, symbol: str, today: date, atm_iv: float) -> None:
        """Maintain rolling IV history for IV rank calculation."""
        if symbol not in self._iv_history:
            self._iv_history[symbol] = []
        history = self._iv_history[symbol]
        # Add today's IV if not already present
        if not history or history[-1][0] != today:
            history.append((today, atm_iv))
        # Keep only last 252 trading days
        cutoff = today - timedelta(days=365)
        self._iv_history[symbol] = [(d, iv) for d, iv in history if d >= cutoff]

    def load_iv_history_from_df(self, symbol: str, iv_series: pd.Series) -> None:
        """
        Bootstrap IV history from a historical series (for backtesting).
        iv_series: DatetimeIndex → float (ATM IV per day)
        """
        self._iv_history[symbol] = [
            (ts.date() if hasattr(ts, "date") else ts, float(iv))
            for ts, iv in iv_series.items()
            if not pd.isna(iv)
        ]
        logger.info(
            "Loaded %d days of IV history for %s",
            len(self._iv_history[symbol]), symbol,
        )

    @staticmethod
    def _compute_iv_rank(iv_series: pd.Series, current_iv: float) -> float:
        window = iv_series.iloc[-IV_HISTORY_LOOKBACK:]
        lo, hi = float(window.min()), float(window.max())
        if hi == lo:
            return 50.0
        return round(((current_iv - lo) / (hi - lo)) * 100, 2)

    @staticmethod
    def _compute_iv_percentile(iv_series: pd.Series, current_iv: float) -> float:
        window = iv_series.iloc[-IV_HISTORY_LOOKBACK:]
        return round(float((window < current_iv).mean() * 100), 2)

    def _build_fallback_surface(
        self, symbol: str, spot_price: float, rv_20d: float,
        atm_iv: float, warnings: list[str],
    ) -> IVSurfaceSnapshot:
        """Minimal surface when no chain data is available."""
        iv_rank = min(max((atm_iv - 0.10) / 0.30 * 100, 0), 100)
        return IVSurfaceSnapshot(
            underlying=symbol, spot_price=spot_price,
            fetched_at=datetime.now(timezone.utc),
            iv_rank=round(iv_rank, 2), iv_percentile=round(iv_rank, 2),
            atm_iv=atm_iv, realized_vol_20d=rv_20d,
            vrp=round(atm_iv - rv_20d, 4),
            front_skew=None, back_skew=None, skew_trend=0.0,
            term_structure=None, data_quality="fallback", warnings=warnings,
        )
