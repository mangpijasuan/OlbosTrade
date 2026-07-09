"""
Options Scan Engine — generates ranked spread candidates by Expected Value (EV).

Integrates Black-Scholes pricing, options intelligence, and automated gates to produce
high-quality spread candidates for autopilot decision logic. Ranks by EV instead of IV
percentile to reflect true risk-reward.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class OptionsScanCandidate:
    """A ranked options spread candidate with full intelligence."""
    id: str
    ticker: str
    option_type: str
    short_strike: float
    long_strike: float
    expiration: str
    dte: int
    credit: float
    max_loss: float
    pop: float
    expected_value: float
    ev_per_risk: float
    kelly_fraction: float
    short_delta: float
    reward_risk: float

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "option_type": self.option_type,
            "short_strike": self.short_strike,
            "long_strike": self.long_strike,
            "expiration": self.expiration,
            "dte": self.dte,
            "credit": self.credit,
            "max_loss": self.max_loss,
            "pop": round(self.pop, 4),
            "expected_value": self.expected_value,
            "ev_per_risk": round(self.ev_per_risk, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "short_delta": round(self.short_delta, 4),
            "reward_risk": round(self.reward_risk, 4),
        }


@dataclass
class OptionsScanResult:
    """Result of an options scan."""
    candidates: list[OptionsScanCandidate]
    gate_blocked: bool
    gate_reason: Optional[str]
    spot: Optional[float]
    vix_estimate: Optional[float]
    realized_vol: Optional[float]
    error: Optional[str]


async def check_no_trade_gate() -> Optional[str]:
    """
    Check if trading is allowed. Returns None if OK to trade, or a reason string if gated.
    Gates checked:
    - Kill switch engaged
    - Market hours (if configured)
    """
    from app.services.kill_switch import kill_switch_service
    from app.utils.market_hours import market_status
    from app.core.config import settings

    if kill_switch_service.is_engaged:
        return f"Kill switch engaged: {kill_switch_service.status.get('reason', 'unknown')}"

    if settings.market_hours_only:
        mkt = market_status()
        if not mkt["is_open"]:
            return f"Market closed: {mkt['reason']}"

    return None


async def _yf_bars(ticker: str, limit: int = 60) -> list:
    """Fetch daily OHLCV bars via yfinance."""
    import yfinance as yf
    from decimal import Decimal
    from app.broker.broker_interface import Bar

    loop = asyncio.get_running_loop()

    def _fetch():
        sym = "^VIX" if ticker.upper() == "VIX" else ticker
        period = f"{min(limit * 2, 730)}d"
        hist = yf.Ticker(sym).history(period=period, auto_adjust=True)
        if hist.empty:
            return []
        hist = hist.tail(limit)
        bars = []
        import math as _math
        for ts, row in hist.iterrows():
            try:
                o = float(row["Open"])
                h = float(row["High"])
                lo = float(row["Low"])
                c = float(row["Close"])
            except (TypeError, ValueError):
                continue
            if any(_math.isnan(x) or x <= 0 for x in (o, h, lo, c)):
                continue
            try:
                bars.append(Bar(
                    timestamp=ts.to_pydatetime(),
                    open=Decimal(str(round(o, 4))),
                    high=Decimal(str(round(h, 4))),
                    low=Decimal(str(round(lo, 4))),
                    close=Decimal(str(round(c, 4))),
                    volume=int(row.get("Volume", 0) or 0),
                ))
            except Exception:
                continue
        return bars

    return await loop.run_in_executor(None, _fetch)


async def scan_options(
    ticker: str = "SPY",
    strategy: str = "bull_put_spread",
    dte_target: Optional[int] = None,
    limit: int = 10,
) -> OptionsScanResult:
    """
    Scan options spreads for the given ticker.
    Returns candidates ranked by Expected Value (EV) in descending order.
    Applies NO-TRADE gate before scanning.

    Args:
        ticker: Underlying symbol (default: SPY)
        strategy: Strategy type (default: bull_put_spread)
        dte_target: Days to expiry target (uses config if None)
        limit: Max candidates to return (default: 10)

    Returns:
        OptionsScanResult with ranked candidates or gate block reason
    """
    from app.core.config import settings
    from app.services.options_pricer import BlackScholesPricer
    from app.services.options_intelligence import analyze_spread
    import uuid

    gate_reason = await check_no_trade_gate()
    if gate_reason:
        return OptionsScanResult(
            candidates=[],
            gate_blocked=True,
            gate_reason=gate_reason,
            spot=None,
            vix_estimate=None,
            realized_vol=None,
            error=None,
        )

    try:
        pricer = BlackScholesPricer()
        candidates = []
        RISK_FREE = 0.05

        if dte_target is None:
            dte_target = settings.get("dte_target", 30)

        # Fetch market data
        bars = await _yf_bars(ticker, limit=60)
        if len(bars) < 20:
            return OptionsScanResult(
                candidates=[],
                gate_blocked=False,
                gate_reason=None,
                spot=None,
                vix_estimate=None,
                realized_vol=None,
                error="Insufficient market data",
            )

        closes = [float(b.close) for b in bars]
        spot = closes[-1]
        log_rets = np.diff(np.log(closes))
        sigma = float(np.std(log_rets) * np.sqrt(252))

        # Estimate IV from VIX if scanning SPY
        vix_est = sigma
        if ticker.upper() == "SPY":
            try:
                vix_bars = await _yf_bars("VIX", limit=20)
                if vix_bars:
                    vix_val = float(vix_bars[-1].close)
                    vix_est = vix_val / 100.0
            except Exception:
                pass

        # Target expiry
        today = date.today()
        target_exp = today + timedelta(days=dte_target)
        while target_exp.weekday() != 4:  # Friday
            target_exp += timedelta(days=1)
        T = max((target_exp - today).days / 365, 0.01)

        # Strategy and option type
        opt_type = "put" if "put" in strategy else "call"

        # Generate candidates across strike grid, sorted by delta
        strike_offsets = [-40, -30, -20, -10, 0, 10, 20, 30, 40]
        for offset in strike_offsets:
            try:
                short_strike = round(spot + offset, 0)
                long_strike = short_strike - 5.0 if opt_type == "put" else short_strike + 5.0
                spread_width = abs(short_strike - long_strike)

                if spread_width <= 0:
                    continue

                # Compute delta for this strike
                delta = pricer.delta(spot, short_strike, T, RISK_FREE, vix_est, opt_type)
                if abs(delta) < 0.10 or abs(delta) > 0.80:
                    continue

                # Black-Scholes pricing
                if opt_type == "put":
                    short_px = pricer.put_price(spot, short_strike, T, RISK_FREE, vix_est)
                    long_px = pricer.put_price(spot, long_strike, T, RISK_FREE, vix_est)
                else:
                    short_px = pricer.call_price(spot, short_strike, T, RISK_FREE, vix_est)
                    long_px = pricer.call_price(spot, long_strike, T, RISK_FREE, vix_est)

                net_credit_ps = short_px - long_px
                if net_credit_ps <= 0.05:
                    continue

                # Analyze with options intelligence
                intel = analyze_spread(
                    spot=spot,
                    short_strike=short_strike,
                    long_strike=long_strike,
                    option_type=opt_type,
                    dte=float(dte_target),
                    iv=vix_est,
                    credit_per_share=net_credit_ps,
                    r=RISK_FREE,
                )

                candidate = OptionsScanCandidate(
                    id=str(uuid.uuid4()),
                    ticker=ticker.upper(),
                    option_type=opt_type,
                    short_strike=float(short_strike),
                    long_strike=float(long_strike),
                    expiration=target_exp.isoformat(),
                    dte=dte_target,
                    credit=round(net_credit_ps * 100, 2),
                    max_loss=intel.max_loss,
                    pop=intel.pop,
                    expected_value=intel.expected_value,
                    ev_per_risk=intel.ev_per_risk,
                    kelly_fraction=intel.kelly_fraction,
                    short_delta=abs(delta),
                    reward_risk=intel.reward_risk,
                )
                candidates.append(candidate)

            except Exception as e:
                logger.debug("Spread generation failed for offset %s: %s", offset, e)
                continue

        # Sort by EV descending (highest EV first)
        candidates.sort(key=lambda c: c.expected_value, reverse=True)

        return OptionsScanResult(
            candidates=candidates[:limit],
            gate_blocked=False,
            gate_reason=None,
            spot=round(spot, 2),
            vix_estimate=round(vix_est * 100, 1),
            realized_vol=round(sigma * 100, 1),
            error=None,
        )

    except Exception as exc:
        logger.warning("Options scan failed: %s", exc, exc_info=True)
        return OptionsScanResult(
            candidates=[],
            gate_blocked=False,
            gate_reason=None,
            spot=None,
            vix_estimate=None,
            realized_vol=None,
            error=str(exc),
        )
