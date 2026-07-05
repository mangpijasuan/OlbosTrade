"""
Chart Intelligence routes — /api/chart (all read-only).

Market bias, multi-timeframe alignment, and market structure. Chart signals are
evidence only — none of these endpoints touch the order path, risk engine,
guardrails, kill switch, or macro gate.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app.services.chart import bars as bars_svc
from app.services.chart.market_bias import BiasInputs, assemble_bias
from app.services.chart.market_structure import analyze_structure
from app.services.chart.timeframe_alignment import (
    TIMEFRAMES, align, classify_timeframe,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_ALIGN_TFS = ["15m", "1h", "4h", "1d", "1w"]  # 5m omitted from headline alignment


async def _bars(symbol: str, tf: str) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, bars_svc.fetch_bars, symbol, tf)


def _rsi(closes: list[float], window: int = 14) -> float | None:
    if len(closes) < window + 1:
        return None
    gains = losses = 0.0
    for i in range(-window, 0):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / window) / (losses / window)
    return round(100 - 100 / (1 + rs), 1)


def _atr_pct(bars: list[dict], window: int = 14) -> float | None:
    if len(bars) < window + 1:
        return None
    trs = []
    for i in range(-window, 0):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs) / len(trs)
    last = bars[-1]["close"] or 1.0
    return round(atr / last * 100, 2)


def _rel_volume(bars: list[dict], window: int = 20) -> float | None:
    if len(bars) < window + 1:
        return None
    avg = sum(b["volume"] for b in bars[-window - 1:-1]) / window
    return round(bars[-1]["volume"] / avg, 2) if avg > 0 else None


async def _macro_risk() -> str:
    try:
        from app.services.event_risk_service import list_macro_events
        events = list_macro_events(days_ahead=3)
        if not events:
            return "low"
        top = min(events, key=lambda e: e["days_away"])
        return top["severity"] if top["days_away"] <= 2 else "moderate"
    except Exception:
        return "low"


@router.get("/alignment/{symbol}")
async def alignment(symbol: str, strategy: str = "default"):
    sym = symbol.upper()
    states = []
    for tf in _ALIGN_TFS:
        b = await _bars(sym, tf)
        states.append(classify_timeframe(tf, b))
    result = align(states, strategy)
    return {"symbol": sym, "strategy": strategy, **result.to_dict()}


@router.get("/structure/{symbol}")
async def structure(symbol: str, timeframe: str = "1d"):
    sym = symbol.upper()
    b = await _bars(sym, timeframe)
    return {"symbol": sym, "timeframe": timeframe, **analyze_structure(b).to_dict()}


@router.get("/bias/{symbol}")
async def bias(symbol: str, strategy: str = "default"):
    sym = symbol.upper()

    # Multi-timeframe alignment.
    states = []
    for tf in _ALIGN_TFS:
        states.append(classify_timeframe(tf, await _bars(sym, tf)))
    align_res = align(states, strategy)

    # Daily context for structure + indicators.
    daily = await _bars(sym, "1d")
    struct = analyze_structure(daily)
    closes = [b["close"] for b in daily]
    price = closes[-1] if closes else None

    # Intraday VWAP relationship (session-ish) from 15m bars.
    intraday = await _bars(sym, "15m")
    above_vwap = None
    if intraday:
        tpv = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in intraday[-26:])
        vol = sum(b["volume"] for b in intraday[-26:])
        if vol > 0:
            vwap = tpv / vol
            above_vwap = intraday[-1]["close"] > vwap

    result = assemble_bias(BiasInputs(
        symbol=sym,
        price=price,
        alignment=align_res,
        structure=struct,
        rsi=_rsi(closes),
        above_vwap=above_vwap,
        relative_volume=_rel_volume(daily),
        atr_pct=_atr_pct(daily),
        regime=await _current_regime(),
        macro_risk=await _macro_risk(),
        data_freshness_s=bars_svc.freshness_seconds(daily),
    ))
    return result.to_dict()


async def _current_regime() -> str | None:
    try:
        from app.api.routes import market_data  # regime endpoint source
        # regime is cached on the app; fall back to None if unavailable.
        import app.main as main_mod
        reg = getattr(main_mod, "_current_regime", None)
        return getattr(reg, "regime", None) if reg else None
    except Exception:
        return None
