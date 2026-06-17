"""Market data routes."""
import asyncio
from datetime import datetime

from fastapi import APIRouter

from app.broker.broker_factory import get_broker
from app.core.config import settings

# yfinance is used for all price display (ticker strip, snapshots).
# IBKR market data requires a paid subscription — we use IBKR only for
# order execution, account data, and options chain data.

router = APIRouter()


async def _yfinance_snapshot(symbol: str) -> dict:
    """
    Fallback price snapshot using yfinance (free, no subscription needed).
    Returns last close + previous close for change_pct calculation.
    Runs in a thread pool to avoid blocking the asyncio event loop.
    """
    import yfinance as yf
    loop = asyncio.get_running_loop()

    def _fetch():
        hist = yf.Ticker(symbol).history(period="5d", auto_adjust=True)
        if hist.empty:
            return {}
        closes = hist["Close"].dropna()
        if len(closes) < 1:
            return {}
        last       = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else last
        chg_pct    = round((last - prev_close) / prev_close * 100, 2)
        return {
            "symbol":     symbol,
            "bid":        None,
            "ask":        None,
            "mid":        last,
            "last_close": last,
            "prev_close": prev_close,
            "change_pct": chg_pct,
            "spread":     None,
            "timestamp":  datetime.utcnow().isoformat(),
            "source":     "yfinance",
        }

    return await loop.run_in_executor(None, _fetch)


@router.get("/snapshot/{symbol}")
async def get_snapshot(symbol: str):
    """
    Return latest price snapshot for a symbol via yfinance.

    IBKR is used only for order execution and account data — not for
    price display, which requires a paid market data subscription.
    yfinance gives free end-of-day prices (and intraday when market is open)
    with no subscription needed.
    """
    try:
        data = await _yfinance_snapshot(symbol)
        if data:
            return data
        return {"symbol": symbol, "error": "No data returned"}
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)}


@router.get("/options-chain/{symbol}")
async def get_options_chain(symbol: str, expiry: str = ""):
    """Fetch live options chain from IBKR for the given symbol and expiry."""
    if not expiry:
        # Default to nearest monthly expiry (~30 DTE)
        from datetime import date, timedelta
        today = date.today()
        # Find next third Friday
        d = today + timedelta(days=30)
        while d.weekday() != 4:  # Friday
            d += timedelta(days=1)
        expiry = d.strftime("%Y-%m-%d")
    try:
        broker = get_broker()
        chain  = await broker.get_options_chain(symbol, expiry)
        return {
            "symbol":           symbol,
            "expiry":           expiry,
            "underlying_price": float(chain.underlying_price),
            "fetched_at":       chain.fetched_at.isoformat(),
            "calls": [
                {
                    "strike":        float(c.strike),
                    "bid":           float(c.bid),
                    "ask":           float(c.ask),
                    "last":          float(c.last),
                    "volume":        c.volume,
                    "open_interest": c.open_interest,
                    "delta":         c.greeks.delta if c.greeks else None,
                    "iv":            c.greeks.implied_vol if c.greeks else None,
                }
                for c in chain.calls
            ],
            "puts": [
                {
                    "strike":        float(p.strike),
                    "bid":           float(p.bid),
                    "ask":           float(p.ask),
                    "last":          float(p.last),
                    "volume":        p.volume,
                    "open_interest": p.open_interest,
                    "delta":         p.greeks.delta if p.greeks else None,
                    "iv":            p.greeks.implied_vol if p.greeks else None,
                }
                for p in chain.puts
            ],
        }
    except Exception as exc:
        return {"symbol": symbol, "expiry": expiry, "error": str(exc)}


@router.get("/iv-rank/{symbol}")
async def get_iv_rank(symbol: str):
    """
    Compute IV rank for a symbol using 60 days of daily bar ATR as a vol proxy.
    True IV rank requires options chain history; this is a fast approximation.
    """
    try:
        broker  = get_broker()
        bars    = await broker.get_bars(symbol, timeframe="1Day", limit=252)
        if len(bars) < 30:
            return {"symbol": symbol, "iv_rank": None, "error": "insufficient data"}

        import pandas as pd, numpy as np
        close = pd.Series([float(b.close) for b in bars])
        high  = pd.Series([float(b.high)  for b in bars])
        low   = pd.Series([float(b.low)   for b in bars])

        # ATR-based realized vol as IV proxy
        tr   = pd.concat([high - low,
                          (high - close.shift()).abs(),
                          (low  - close.shift()).abs()], axis=1).max(axis=1)
        atr  = tr.rolling(14).mean()
        rv   = (atr / close * np.sqrt(252) * 100)   # annualised % vol

        rv_now  = float(rv.iloc[-1])
        rv_high = float(rv.max())
        rv_low  = float(rv.min())
        iv_rank = round((rv_now - rv_low) / max(rv_high - rv_low, 0.01) * 100, 1)

        # Use regime VIX if available for context
        from app.main import _current_regime
        vix = None
        if _current_regime and _current_regime.features_used:
            vix = _current_regime.features_used.vix

        return {
            "symbol":       symbol,
            "iv_rank":      iv_rank,
            "iv_now_pct":   round(rv_now, 1),
            "iv_high_pct":  round(rv_high, 1),
            "iv_low_pct":   round(rv_low, 1),
            "vix":          vix,
            "method":       "atr_rv_proxy",
        }
    except Exception as exc:
        return {"symbol": symbol, "iv_rank": None, "error": str(exc)}


@router.get("/regime")
async def get_regime():
    """Return current regime classification and active strategies."""
    from app.main import _current_regime
    if _current_regime is None:
        return {
            "regime": "unknown",
            "description": "Regime not yet classified",
            "equity_allowed": False,
            "options_allowed": False,
            "equity_strategies": [],
            "options_strategies": [],
            "equity_size_multiplier": 0.5,
            "options_size_multiplier": 0.5,
        }
    vix = None
    iv_rank = None
    if _current_regime.features_used:
        vix     = round(_current_regime.features_used.vix, 2)
        iv_rank = round(_current_regime.features_used.iv_rank, 1)

    return {
        "regime":                  _current_regime.regime.value,
        "description":             _current_regime.description,
        "confidence":              _current_regime.confidence,
        "equity_allowed":          _current_regime.equity_allowed,
        "options_allowed":         _current_regime.options_allowed,
        "equity_strategies":       _current_regime.equity_strategies_allowed,
        "options_strategies":      _current_regime.strategies_allowed,
        "equity_size_multiplier":  _current_regime.equity_size_multiplier,
        "options_size_multiplier": _current_regime.options_size_multiplier,
        "classified_at":           _current_regime.classified_at.isoformat(),
        "vix":                     vix,
        "iv_rank":                 iv_rank,
    }


@router.get("/greeks")
async def get_portfolio_greeks():
    """Return current portfolio-level Greeks snapshot."""
    from app.main import _greeks_tracker
    if _greeks_tracker is None:
        return {"net_delta": 0.0, "net_vega": 0.0, "net_theta": 0.0}
    return _greeks_tracker.snapshot()


@router.get("/broker")
async def get_broker_status():
    """Return active broker name and connection status."""
    try:
        broker = get_broker()
        is_paper = "paper" in settings.alpaca_base_url if settings.broker == "alpaca" \
                   else settings.ibkr_port in (7497, 4002)
        connected = True
        if settings.broker == "ibkr":
            connected = bool(getattr(broker, "_connected", False))
            if hasattr(broker, "ib"):
                connected = connected and bool(broker.ib.isConnected())
        return {
            "broker":           settings.broker,
            "supports_options": broker.supports_options,
            "supports_equities": broker.supports_equities,
            "paper_mode":       is_paper,
            "status":           "connected" if connected else "disconnected",
        }
    except Exception as exc:
        return {
            "broker": settings.broker,
            "status": "error",
            "error":  str(exc),
        }
