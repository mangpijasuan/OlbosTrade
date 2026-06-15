"""
IV overlay — uses options market data to improve equity signal quality.
Put/call ratio, IV rank, and skew provide institutional-flow context.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.broker.broker_interface import BrokerInterface
    from app.services.iv_surface import IVSurfaceSnapshot

logger = logging.getLogger(__name__)


async def get_iv_signal_boost(
    ticker: str,
    broker: "BrokerInterface",
    iv_surface_builder=None,
) -> dict:
    """
    Compute an IV-based signal boost for equity entries.

    Returns:
        boost:  float in [-0.5, +0.5] added to equity signal confidence
        reason: human-readable explanation
        put_call_ratio: float
        iv_rank: float
        size_scale: float — multiply position size by this (0.75 if IV rank > 70)
    """
    if not broker.supports_options:
        return {
            "boost": 0.0,
            "reason": "n/a — broker does not support options",
            "put_call_ratio": None,
            "iv_rank": None,
            "size_scale": 1.0,
        }

    try:
        # Use nearest weekly expiry
        today = date.today()
        days_to_friday = (4 - today.weekday()) % 7
        if days_to_friday == 0:
            days_to_friday = 7
        expiry = (today + timedelta(days=days_to_friday)).isoformat()

        chain = await broker.get_options_chain(ticker, expiry)

        calls_oi = sum(c.open_interest for c in chain.calls)
        puts_oi  = sum(p.open_interest for p in chain.puts)

        put_call_ratio = puts_oi / max(calls_oi, 1)

        boost = 0.0
        reasons = []

        if put_call_ratio > 1.5:
            boost -= 0.3
            reasons.append(f"P/C ratio {put_call_ratio:.2f} > 1.5 (bearish institutional hedging)")
        elif put_call_ratio < 0.6:
            boost += 0.3
            reasons.append(f"P/C ratio {put_call_ratio:.2f} < 0.6 (bullish call buying)")

        # IV rank from surface if available
        iv_rank = None
        size_scale = 1.0
        if iv_surface_builder is not None:
            try:
                surface = iv_surface_builder.latest
                if surface is not None:
                    iv_rank = surface.iv_rank
                    if iv_rank > 70:
                        size_scale = 0.75
                        reasons.append(f"IV rank {iv_rank:.0f} > 70 — reducing position size 25%")
            except Exception:
                pass

        # Put skew: elevated put IV relative to call IV = institutional hedging = bearish
        try:
            atm_strike = float(chain.underlying_price)
            atm_puts  = [p for p in chain.puts  if abs(float(p.strike) - atm_strike) < atm_strike * 0.05]
            atm_calls = [c for c in chain.calls if abs(float(c.strike) - atm_strike) < atm_strike * 0.05]
            if atm_puts and atm_calls:
                avg_put_iv  = sum(p.greeks.implied_vol for p in atm_puts  if p.greeks) / max(len(atm_puts), 1)
                avg_call_iv = sum(c.greeks.implied_vol for c in atm_calls if c.greeks) / max(len(atm_calls), 1)
                skew = avg_put_iv - avg_call_iv
                if skew > 0.05:
                    boost -= 0.2
                    reasons.append(f"Put skew {skew:.2%} elevated — bearish equity bias")
        except Exception:
            pass

        boost = max(-0.5, min(0.5, boost))
        return {
            "boost": round(boost, 4),
            "reason": "; ".join(reasons) if reasons else "neutral",
            "put_call_ratio": round(put_call_ratio, 3),
            "iv_rank": iv_rank,
            "size_scale": size_scale,
        }

    except NotImplementedError:
        return {"boost": 0.0, "reason": "n/a", "put_call_ratio": None, "iv_rank": None, "size_scale": 1.0}
    except Exception as exc:
        logger.warning("IV overlay failed for %s: %s — using boost=0.0", ticker, exc)
        return {"boost": 0.0, "reason": f"error: {exc}", "put_call_ratio": None, "iv_rank": None, "size_scale": 1.0}
