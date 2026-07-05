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


async def _confirmation_for(symbol: str, strategy: str) -> dict:
    """Assemble the trade-confirmation score for one symbol (read-only)."""
    from app.services.chart.breakout_confirmation import BreakoutInputs, assess_breakout
    from app.services.chart.confirmation_score import ScoreInputs, compute_confirmation_score
    from app.services.chart.setup_scanner import strategy_fit_for

    sym = symbol.upper()
    states = [classify_timeframe(tf, await _bars(sym, tf)) for tf in _ALIGN_TFS]
    align_res = align(states, strategy)

    daily = await _bars(sym, "1d")
    struct = analyze_structure(daily)
    closes = [b["close"] for b in daily]
    price = closes[-1] if closes else None
    rvol = _rel_volume(daily)
    atrp = _atr_pct(daily)
    macro = await _macro_risk()

    structure_agrees = (
        (align_res.dominant == "bullish" and struct.state == "uptrend")
        or (align_res.dominant == "bearish" and struct.state == "downtrend")
    )

    # Breakout vs nearest resistance from structure (closed daily bar).
    breakout_confirmed = False
    if price is not None and struct.resistance and align_res.dominant == "bullish":
        level = min(r for r in struct.resistance)
        bo = assess_breakout(BreakoutInputs(
            kind="breakout", close=price, level=level, closed_bar=True,
            relative_volume=rvol, above_vwap=True,
            mtf_agrees=(align_res.dominant == "bullish"),
            event_clear=(macro not in ("high", "very_high")),
        ))
        breakout_confirmed = bo.status == "confirmed"

    regime = await _current_regime()
    regime_fit = bool(regime and "trend" in regime and align_res.dominant != "neutral")

    dq = None
    try:
        from app.services.intel.provider_registry import registry
        dq = registry.data_quality(sym).score
    except Exception:
        pass

    score = compute_confirmation_score(ScoreInputs(
        alignment_score=align_res.score, alignment_max=align_res.max_score,
        dominant=align_res.dominant, structure_agrees=structure_agrees,
        breakout_confirmed=breakout_confirmed, relative_volume=rvol,
        above_vwap=None, atr_pct=atrp, regime_fit=regime_fit, macro_risk=macro,
        portfolio_overlap_pct=None, data_quality=dq,
    ))

    return {
        "symbol": sym,
        "bias": align_res.dominant,
        "structure_state": struct.state,
        "timeframe_alignment": f"{align_res.bullish_count} of {align_res.total} bullish",
        "macro_risk": macro,
        "strategy_fit": strategy_fit_for(align_res.dominant, struct.state),
        "confirmation": score.to_dict(),
    }


@router.get("/confirmation/{symbol}")
async def confirmation(symbol: str, strategy: str = "default"):
    return await _confirmation_for(symbol, strategy)


@router.get("/scanner")
async def scanner(watchlist: str = "SPY,QQQ,AAPL,NVDA,TSLA,AMD", strategy: str = "default",
                  min_confirmation: int = 60):
    from app.services.chart.setup_scanner import SetupCandidate, rank_setups

    symbols = [s.strip().upper() for s in watchlist.split(",") if s.strip()][:12]
    assessments = await asyncio.gather(*[_confirmation_for(s, strategy) for s in symbols])
    candidates = [
        SetupCandidate(
            symbol=a["symbol"], bias=a["bias"],
            confirmation_score=a["confirmation"]["score"],
            structure_state=a["structure_state"],
            timeframe_alignment=a["timeframe_alignment"],
            macro_risk=a["macro_risk"], portfolio_overlap_pct=None,
            min_confirmation=min_confirmation, strategy_fit=a["strategy_fit"],
        )
        for a in assessments
    ]
    return {"strategy": strategy, "results": [r.to_dict() for r in rank_setups(candidates)]}


async def _current_regime() -> str | None:
    try:
        from app.api.routes import market_data  # regime endpoint source
        # regime is cached on the app; fall back to None if unavailable.
        import app.main as main_mod
        reg = getattr(main_mod, "_current_regime", None)
        return getattr(reg, "regime", None) if reg else None
    except Exception:
        return None
