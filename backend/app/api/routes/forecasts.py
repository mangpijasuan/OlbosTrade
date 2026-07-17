"""Read-only Scenario Lab forecast routes."""
from __future__ import annotations

import asyncio
import math

from fastapi import APIRouter, HTTPException, Query

from app.services.probability_forecast_engine import ForecastBar, SUPPORTED_HORIZONS, generate_forecast

router = APIRouter()


def _load_daily_bars(symbol: str, limit: int = 120) -> list[ForecastBar]:
    import yfinance as yf

    history = yf.Ticker(symbol).history(period="1y", auto_adjust=True).tail(limit)
    bars: list[ForecastBar] = []
    for _, row in history.iterrows():
        try:
            close, high, low = float(row["Close"]), float(row["High"]), float(row["Low"])
            volume = float(row.get("Volume", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v > 0 for v in (close, high, low)):
            continue
        bars.append(ForecastBar(close=close, high=high, low=low, volume=max(0.0, volume)))
    return bars


@router.get("/symbols/{symbol}")
async def symbol_forecast(symbol: str, horizon: int = Query(default=5)):
    """Return a research-only scenario outlook; this endpoint cannot execute."""
    if horizon not in SUPPORTED_HORIZONS:
        raise HTTPException(status_code=422, detail=f"horizon must be one of {SUPPORTED_HORIZONS}")
    try:
        bars = await asyncio.to_thread(_load_daily_bars, symbol.strip().upper())
        return generate_forecast(symbol, horizon, bars)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"forecast data unavailable: {exc}") from exc
