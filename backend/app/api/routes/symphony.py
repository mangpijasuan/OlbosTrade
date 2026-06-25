"""
Symphony routes — Composer-style composable strategies.

  GET  /api/symphony/examples            list ready-made example strategies
  POST /api/symphony/validate            validate a strategy tree (dry-run)
  POST /api/symphony/backtest            instant backtest over yfinance history
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.symphony import (
    StrategyError,
    collect_tickers,
    evaluate,
    example_strategies,
    normalize,
    run_backtest,
)

router = APIRouter()


class BacktestRequest(BaseModel):
    tree: dict
    start: Optional[str] = None          # YYYY-MM-DD (default: 3y ago)
    end: Optional[str] = None            # YYYY-MM-DD (default: today)
    cadence: str = "weekly"              # daily | weekly | monthly
    starting_capital: float = 10000.0


class ValidateRequest(BaseModel):
    tree: dict


async def _fetch_closes(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Daily adjusted closes for all tickers as one DataFrame (index=date)."""
    import yfinance as yf
    loop = asyncio.get_running_loop()

    def _fetch() -> pd.DataFrame:
        cols = {}
        for tk in tickers:
            sym = "^VIX" if tk.upper() == "VIX" else tk
            hist = yf.Ticker(sym).history(start=start.isoformat(),
                                          end=(end + timedelta(days=1)).isoformat(),
                                          auto_adjust=True)
            if not hist.empty:
                s = hist["Close"].dropna()
                s.index = pd.to_datetime(s.index).tz_localize(None)
                cols[tk] = s
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(cols).sort_index()

    return await loop.run_in_executor(None, _fetch)


@router.get("/examples")
async def get_examples():
    return {"examples": example_strategies()}


@router.post("/validate")
async def validate(req: ValidateRequest):
    """Static + light dynamic validation: structure, tickers, and a dry-run evaluate."""
    try:
        tickers = sorted(collect_tickers(req.tree))
        if not tickers:
            return {"valid": False, "error": "strategy references no tickers"}
        # Dry-run on recent data to catch structural / indicator errors.
        end = date.today()
        start = end - timedelta(days=400)
        closes = await _fetch_closes(tickers, start, end)
        if closes.empty:
            return {"valid": False, "error": f"no price data for {tickers}"}
        asof = {t: closes[t].dropna() for t in closes.columns}
        weights = normalize(evaluate(req.tree, asof))
        return {"valid": True, "tickers": tickers, "current_target_weights": weights}
    except StrategyError as exc:
        return {"valid": False, "error": str(exc)}
    except Exception as exc:
        return {"valid": False, "error": f"unexpected: {exc}"}


@router.post("/backtest")
async def backtest(req: BacktestRequest):
    """Instant backtest of a strategy tree over historical data."""
    try:
        tickers = sorted(collect_tickers(req.tree))
        if not tickers:
            return {"error": "strategy references no tickers"}

        end = date.fromisoformat(req.end) if req.end else date.today()
        start = date.fromisoformat(req.start) if req.start else end - timedelta(days=365 * 3)
        # Fetch extra warm-up history so indicators (e.g. SMA-200) are valid at start.
        fetch_start = start - timedelta(days=400)

        closes = await _fetch_closes(tickers, fetch_start, end)
        if closes.empty:
            return {"error": f"no price data for {tickers}"}

        missing = [t for t in tickers if t not in closes.columns]
        result = run_backtest(
            req.tree, closes, start, end,
            cadence=req.cadence, starting_capital=req.starting_capital,
        )
        return {
            "tickers": tickers,
            "missing_tickers": missing,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "cadence": req.cadence,
            "starting_capital": req.starting_capital,
            **result,
        }
    except StrategyError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"unexpected: {exc}"}
