"""
Equity trading API routes.
All signals pass through the UnifiedRiskEngine before execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_admin_api_key
from app.broker.broker_factory import get_broker
from app.core.config import settings
from app.services.equity_signal_engine import (
    compute_equity_trade_plan,
    compute_indicators,
    earnings_gate,
    score_equity_signal,
)
from app.services.iv_overlay import get_iv_signal_boost
from app.services.orderflow_engine import get_orderflow_score

router = APIRouter()

# In-memory signal store (replace with DB queries for production)
_recent_signals: list[dict] = []


async def _yf_bars_route(ticker: str, limit: int = 120):
    """Fetch bars from yfinance — no broker connection required."""
    import asyncio
    import yfinance as yf
    from decimal import Decimal
    from app.broker.broker_interface import Bar

    loop = asyncio.get_running_loop()

    def _fetch():
        hist = yf.Ticker(ticker).history(period=f"{min(limit * 2, 730)}d", auto_adjust=True)
        hist = hist.tail(limit)
        result = []
        for ts, row in hist.iterrows():
            result.append(Bar(
                timestamp=ts.to_pydatetime(),
                open=Decimal(str(round(float(row["Open"]), 4))),
                high=Decimal(str(round(float(row["High"]), 4))),
                low=Decimal(str(round(float(row["Low"]), 4))),
                close=Decimal(str(round(float(row["Close"]), 4))),
                volume=int(row.get("Volume", 0) or 0),
            ))
        return result

    return await loop.run_in_executor(None, _fetch)


@router.post("/scan", dependencies=[Depends(require_admin_api_key)])
async def scan_equity_signals():
    """
    Run equity signal scan across the configured watchlist.
    Uses yfinance for historical bars — no broker connection required.
    Orderflow and IV boost are attempted from IBKR but degrade gracefully to 0.0.
    """
    watchlist = settings.get_equity_watchlist()
    results = []

    # Broker is optional — only needed for orderflow/IV boost
    try:
        broker = get_broker()
    except Exception:
        broker = None

    for ticker in watchlist:
        try:
            # Earnings gate check
            if earnings_gate(ticker, settings.earnings_gate_days):
                results.append({
                    "ticker": ticker,
                    "action": "HOLD",
                    "reason": "earnings_gate",
                    "earnings_gated": True,
                })
                continue

            # Fetch bars via yfinance — never requires IBKR
            bars = await _yf_bars_route(ticker, limit=120)
            if len(bars) < 30:
                results.append({"ticker": ticker, "action": "HOLD", "reason": "insufficient_data"})
                continue

            import pandas as pd
            df = pd.DataFrame([{
                "open":   float(b.open),
                "high":   float(b.high),
                "low":    float(b.low),
                "close":  float(b.close),
                "volume": b.volume,
            } for b in bars])

            ind = compute_indicators(df)
            if not ind:
                results.append({"ticker": ticker, "action": "HOLD", "reason": "indicator_error"})
                continue

            # Orderflow score — gracefully skip if IBKR not connected
            orderflow = 0.0
            if broker is not None:
                try:
                    orderflow = await get_orderflow_score(ticker, broker)
                except Exception:
                    pass  # IBKR offline — use neutral orderflow

            # IV overlay boost — gracefully skip if IBKR not connected
            iv_boost = 0.0
            if broker is not None:
                try:
                    iv_data = await get_iv_signal_boost(ticker, broker)
                    iv_boost = iv_data.get("boost", 0.0)
                except Exception:
                    pass  # IBKR offline — no IV boost

            action, confidence, reasons = score_equity_signal(
                ind,
                sentiment_score=0.0,
                orderflow_score=orderflow,
            )
            confidence = min(1.0, confidence + iv_boost)

            trade_plan = {}
            if action in ("BUY", "SELL") and confidence >= settings.effective_equity_min_confidence:
                # Use live account value for position sizing; fall back to config
                portfolio_value = settings.starting_capital
                if broker is not None:
                    try:
                        acct = await broker.get_account_summary()
                        portfolio_value = float(acct.net_liquidation or portfolio_value)
                    except Exception:
                        pass
                trade_plan = compute_equity_trade_plan(
                    ind, action,
                    portfolio_value=portfolio_value,
                    sentiment_score=0.0,
                )

            signal = {
                "id":              str(uuid.uuid4()),
                "ticker":          ticker,
                "generated_at":    datetime.now(timezone.utc).isoformat(),
                "action":          action,
                "confidence":      round(confidence, 4),
                "orderflow_score": round(orderflow, 4),
                "iv_overlay_boost": round(iv_boost, 4),
                "earnings_gated":  False,
                "reasons":         reasons,
                "trade_plan":      trade_plan,
                "indicators": {
                    "rsi":         ind.get("rsi"),
                    "macd":        ind.get("macd"),
                    "bb_pct_b":    ind.get("bb_pct_b"),
                    "atr":         ind.get("atr"),
                    "volume_ratio": ind.get("volume_ratio"),
                },
            }
            _recent_signals.insert(0, signal)
            results.append(signal)

        except Exception as exc:
            results.append({"ticker": ticker, "action": "HOLD", "reason": f"error: {exc}"})

    # Keep only last 200 signals in memory
    del _recent_signals[200:]

    return {"scanned": len(watchlist), "signals": results}


@router.get("/signals")
async def list_equity_signals(limit: int = 50):
    """Return recent equity signals (most recent first)."""
    return {"signals": _recent_signals[:limit], "total": len(_recent_signals)}


@router.post("/signals/{signal_id}/approve", dependencies=[Depends(require_admin_api_key)])
async def approve_signal(signal_id: str):
    """Manually approve a pending equity signal."""
    for sig in _recent_signals:
        if sig.get("id") == signal_id:
            sig["approved_at"] = datetime.now(timezone.utc).isoformat()
            return {"status": "approved", "signal": sig}
    raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")


@router.get("/positions")
async def get_equity_positions():
    """Return open equity positions from the active broker."""
    try:
        broker = get_broker()
        if hasattr(broker, "get_equity_positions"):
            positions = await broker.get_equity_positions()
        else:
            positions = []
        return {"positions": positions, "broker": settings.broker}
    except Exception as exc:
        return {"positions": [], "error": str(exc), "broker": settings.broker}
