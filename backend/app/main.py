"""
FastAPI application entry point.
All routes are registered here. Health check at GET /health.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional

from app.utils.logger import get_logger


async def _yf_bars(ticker: str, limit: int = 60) -> list:
    """
    Fetch daily OHLCV bars via yfinance (free, no broker subscription needed).
    Returns a list of Bar-like objects compatible with the existing code.
    Used by regime classifier, equity scan, and options scan instead of IBKR.
    IBKR is reserved for order execution and account data only.
    """
    import yfinance as yf
    from app.broker.broker_interface import Bar

    loop = asyncio.get_running_loop()

    def _fetch():
        sym = "^VIX" if ticker.upper() == "VIX" else ticker
        period = f"{min(limit * 2, 730)}d"   # fetch extra to handle weekends/holidays
        hist = yf.Ticker(sym).history(period=period, auto_adjust=True)
        if hist.empty:
            return []
        hist = hist.tail(limit)
        bars = []
        for ts, row in hist.iterrows():
            bars.append(Bar(
                timestamp=ts.to_pydatetime(),
                open=Decimal(str(round(float(row["Open"]), 4))),
                high=Decimal(str(round(float(row["High"]), 4))),
                low=Decimal(str(round(float(row["Low"]), 4))),
                close=Decimal(str(round(float(row["Close"]), 4))),
                volume=int(row.get("Volume", 0) or 0),
            ))
        return bars

    return await loop.run_in_executor(None, _fetch)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    analytics,
    backtest,
    journal,
    market_data,
    paper_trade,
    research,
    risk,
    strategy,
    trading_mode,
)
from app.api.routes import equity
from app.api.routes import trade_desk
from app.api.routes import symphony
from app.api.routes import options
from app.api.routes import portfolio
from app.core.config import settings

logger = get_logger(__name__)

app = FastAPI(
    title="OlbosQuant",
    version="4.0.0",
    description="Blessed prosperity through disciplined, rules-based quantitative trading.",
)

_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global singletons (populated at startup) ───────────────────────────────
_current_regime: Optional[object] = None   # RegimeState
_greeks_tracker: Optional[object] = None   # PortfolioGreeksTracker
_signal_scorer: Optional[object] = None    # SignalScorer (lazy — loads model pkl)

# Tracks when a DB-open trade was first seen missing from the broker, so we can
# wait for execution data before booking an exit instead of fabricating $0 P&L.
_close_pending: dict[str, datetime] = {}
CLOSE_GRACE_SECONDS = 300   # wait up to 5 min for a real exit price, then book unknown

# Entry-side reconciliation: when a `pending` trade's order is still working we
# wait this long for it to fill. After the window, an order with no broker
# position and no fill execution is treated as terminated-unfilled and the
# pending trade is cancelled (so unfilled/ProgramCancelled limit orders never
# become phantom positions). Generous because DAY limit orders can sit unfilled.
_fill_pending: dict[str, datetime] = {}
FILL_GRACE_SECONDS = 1800   # 30 min for a working order to fill before cancelling

# Heartbeat: monotonic timestamp of the last background-scheduler loop, used by the
# Executive Summary's "Trading Agent — Running" health check.
_scheduler_last_tick: float = 0.0

# ── Route registration ─────────────────────────────────────────────────────
app.include_router(backtest.router,    prefix="/api/backtest",    tags=["Backtest"])
app.include_router(strategy.router,    prefix="/api/strategy",    tags=["Strategy"])
app.include_router(paper_trade.router, prefix="/api/paper-trade", tags=["Paper Trade"])
app.include_router(market_data.router, prefix="/api/market",      tags=["Market Data"])
app.include_router(risk.router,        prefix="/api/risk",         tags=["Risk"])
app.include_router(research.router,    prefix="/api/research",     tags=["Research"])
app.include_router(journal.router,     prefix="/api/journal",      tags=["Journal"])
app.include_router(analytics.router,   prefix="/api/analytics",    tags=["Analytics"])
app.include_router(trading_mode.router,prefix="/api/mode",         tags=["Trading Mode"])
app.include_router(equity.router,      prefix="/api/equity",       tags=["Equity"])
app.include_router(trade_desk.router,  prefix="/api/trade-desk",   tags=["Trade Desk"])
app.include_router(symphony.router,    prefix="/api/symphony",     tags=["Symphony"])
app.include_router(options.router,     prefix="/api/options",      tags=["Options"])
app.include_router(portfolio.router,   prefix="/api/portfolio",    tags=["Portfolio"])


# ── Startup ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup() -> None:
    global _current_regime, _greeks_tracker

    # 1. Initialize broker and connect
    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()
        logger.info(
            "Broker initialized: %s | options=%s equities=%s",
            settings.broker, broker.supports_options, broker.supports_equities,
        )
        # IBKR requires an explicit async connect; Alpaca is stateless REST
        if hasattr(broker, "connect"):
            try:
                await broker.connect()
                logger.info("Broker connected successfully")
            except Exception as conn_exc:
                logger.warning(
                    "Broker connect() failed (will retry on first use): %s", conn_exc
                )

        # Wire kill switch — must happen after broker is available
        from app.services.kill_switch import kill_switch_service
        kill_switch_service.configure(broker)
        # Restore engaged state from DB so a restart can't silently re-enable
        # trading after the kill switch was engaged.
        await kill_switch_service.rehydrate()
        logger.info("Kill switch wired to broker (engaged=%s)", kill_switch_service.is_engaged)
    except Exception as exc:
        logger.warning("Broker initialization failed (non-fatal): %s", exc)

    # 2. Initialize portfolio Greeks tracker
    from app.services.portfolio_greeks import PortfolioGreeksTracker
    _greeks_tracker = PortfolioGreeksTracker()
    logger.info("PortfolioGreeksTracker initialized")

    # 3. Classify regime immediately, then run equity scan
    async def _startup_market_init():
        await _reclassify_regime()
        await _run_equity_scan()
    asyncio.create_task(_startup_market_init())

    # 4. Start background scheduler
    asyncio.create_task(_background_scheduler())


async def _background_scheduler() -> None:
    """Background task that runs periodic scans and updates."""
    global _current_regime, _scheduler_last_tick

    equity_interval_s  = settings.equity_signal_interval_minutes * 60
    options_interval_s = 30 * 60   # 30 minutes
    regime_interval_s  = 30 * 60   # 30 minutes
    greeks_interval_s  = 60        # 1 minute
    fills_interval_s   = 30        # 30 seconds

    import time as _time
    _now = _time.monotonic()
    # Start timers at "now" so the scheduler doesn't fire immediately
    # (startup already ran regime + equity scan)
    last_equity  = _now
    last_options = _now
    last_regime  = _now
    last_greeks  = 0.0   # Greeks update on first tick is fine (lightweight)
    last_fills   = 0.0

    import time

    reconnect_interval_s = 60   # Check broker connection every 60s
    last_reconnect = 0.0

    while True:
        try:
            now = time.monotonic()
            _scheduler_last_tick = now   # heartbeat for the System Health panel
            from app.services.observability import observability as _obs
            _obs.incr("scanner.tick")
            _obs.gauge("scanner.last_tick_monotonic", now)

            # Every 60s: ensure broker is still connected (auto-reconnect)
            if now - last_reconnect >= reconnect_interval_s:
                try:
                    from app.broker.broker_factory import get_broker
                    _broker = get_broker()
                    is_connected = getattr(_broker, "_connected", False)
                    if hasattr(_broker, "ib"):
                        is_connected = is_connected and _broker.ib.isConnected()
                    if not is_connected and hasattr(_broker, "connect"):
                        logger.warning("Broker disconnected — attempting reconnect")
                        await _broker.connect()
                        logger.info("Broker reconnected successfully")
                except Exception as _rc_exc:
                    logger.warning("Broker reconnect failed: %s", _rc_exc)
                last_reconnect = now

            # Every 30 min: regime reclassify
            if now - last_regime >= regime_interval_s:
                await _reclassify_regime()
                last_regime = now

            # Every 15 min: equity signal scan.
            # Run when regime allows equities, OR when regime is not yet classified
            # (treated as UNKNOWN — reduced size, but signals are still generated).
            # Only skip when regime is explicitly CRISIS.
            if now - last_equity >= equity_interval_s:
                regime_blocks_equity = (
                    _current_regime is not None
                    and not getattr(_current_regime, "equity_allowed", True)
                )
                if not regime_blocks_equity:
                    await _run_equity_scan()
                else:
                    logger.info(
                        "Equity scan skipped — regime %s does not allow equities",
                        getattr(_current_regime, "regime_type", "unknown"),
                    )
                last_equity = now

            # Every 1 hour: options spread signal scan (if regime allows)
            if now - last_options >= options_interval_s:
                await _run_options_scan()
                last_options = now

            # Every 30 sec: poll fills from active broker
            if now - last_fills >= fills_interval_s:
                await _poll_fills()
                last_fills = now

            # Every 1 min: update portfolio Greeks
            if now - last_greeks >= greeks_interval_s:
                await _update_portfolio_greeks()
                last_greeks = now

        except Exception as exc:
            logger.error("Background scheduler error: %s", exc)

        await asyncio.sleep(10)


async def _reclassify_regime() -> None:
    """
    Classify current market regime using yfinance for SPY + VIX bars.
    Builds a lightweight IVSurfaceSnapshot from VIX price as an ATM IV proxy —
    no live options chain or broker subscription required.
    """
    global _current_regime
    try:
        import pandas as pd
        import numpy as np
        from datetime import datetime, timezone

        # Use yfinance — free, no broker subscription needed
        spy_bars = await _yf_bars("SPY", limit=60)
        vix_bars = await _yf_bars("VIX", limit=60)

        if len(spy_bars) < 15:
            logger.warning("Regime: insufficient SPY bars (%d) — keeping current", len(spy_bars))
            return

        # Build DataFrames
        spy_close = pd.Series([float(b.close) for b in spy_bars])
        spy_high  = pd.Series([float(b.high)  for b in spy_bars])
        spy_low   = pd.Series([float(b.low)   for b in spy_bars])
        returns   = spy_close.pct_change().dropna()

        # RSI(14)
        delta = spy_close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, 1e-9)
        rsi_val = float((100 - 100 / (1 + rs)).iloc[-1])

        # ADX(14) — simplified
        tr    = pd.concat([
            spy_high - spy_low,
            (spy_high - spy_close.shift()).abs(),
            (spy_low  - spy_close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        dm_p  = spy_high.diff().clip(lower=0)
        dm_m  = (-spy_low.diff()).clip(lower=0)
        di_p  = 100 * dm_p.rolling(14).mean() / atr14.replace(0, 1)
        di_m  = 100 * dm_m.rolling(14).mean() / atr14.replace(0, 1)
        dx    = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, 1)
        adx_val = float(dx.rolling(14).mean().iloc[-1])

        # VIX proxy for IV rank
        if len(vix_bars) >= 5:
            vix_series = pd.Series([float(b.close) for b in vix_bars])
            vix_now    = float(vix_series.iloc[-1])
            vix_high   = float(vix_series.max())
            vix_low    = float(vix_series.min())
            iv_rank    = (vix_now - vix_low) / max(vix_high - vix_low, 0.01) * 100
        else:
            # VIX unavailable — use realized vol as proxy
            rv = float(returns.iloc[-20:].std() * np.sqrt(252)) if len(returns) >= 20 else 0.15
            vix_now = rv * 100
            iv_rank = 30.0  # neutral assumption

        realized_vol = float(returns.iloc[-20:].std() * np.sqrt(252)) if len(returns) >= 20 else 0.15

        # Build minimal IVSurfaceSnapshot (no options chain required)
        from app.services.iv_surface import IVSurfaceSnapshot
        surface = IVSurfaceSnapshot(
            underlying="SPY",
            spot_price=float(spy_close.iloc[-1]),
            fetched_at=datetime.now(timezone.utc),
            iv_rank=iv_rank,
            iv_percentile=iv_rank,
            atm_iv=vix_now / 100.0,
            realized_vol_20d=realized_vol,
            vrp=max(vix_now / 100.0 - realized_vol, 0.0),
            front_skew=None,
            back_skew=None,
            skew_trend=0.0,
            term_structure=None,
            data_quality="partial",
            warnings=["VIX-proxy surface — no live options chain"],
        )

        from app.services.regime_classifier import RegimeClassifier, compute_flow_features
        classifier = RegimeClassifier()
        flow_feats = await compute_flow_features("SPY")
        _current_regime = classifier.classify(
            surface, rsi=rsi_val, adx=adx_val, spy_returns=returns,
            flow_sentiment_score=flow_feats["flow_sentiment_score"],
            flow_large_sweep_bullish_count=flow_feats["flow_large_sweep_bullish_count"],
        )
        logger.info(
            "Regime → %s (VIX=%.1f, IV_rank=%.0f, RSI=%.1f, ADX=%.1f, equity=%s)",
            _current_regime.regime.value, vix_now, iv_rank, rsi_val, adx_val,
            _current_regime.equity_allowed,
        )

    except Exception as exc:
        logger.warning("Regime reclassify failed: %s", exc, exc_info=True)


async def _run_equity_scan() -> None:
    """Background scan — writes results into the same in-memory store as POST /api/equity/scan."""
    try:
        logger.info("Background equity signal scan starting")
        import uuid
        import pandas as pd
        from datetime import datetime, timezone
        from app.broker.broker_factory import get_broker
        from app.services.equity_signal_engine import (
            compute_indicators, compute_equity_trade_plan,
            earnings_gate, score_equity_signal,
        )
        from app.services.orderflow_engine import get_orderflow_score
        from app.api.routes.equity import _recent_signals   # shared in-memory store

        watchlist = settings.get_equity_watchlist()
        routable: list = []   # qualifying signals to rank + route highest-first

        for ticker in watchlist[:5]:   # cap at 5 per background tick
            try:
                if earnings_gate(ticker, settings.earnings_gate_days):
                    continue
                # Use yfinance for historical bars — no broker subscription needed.
                # Need >=200 bars so EMA200 computes; with only 120 it was always
                # NaN, forcing above_ema200=False and skewing every signal bearish.
                bars = await _yf_bars(ticker, limit=250)
                if len(bars) < 30:
                    continue
                df = pd.DataFrame([{
                    "open": float(b.open), "high": float(b.high),
                    "low": float(b.low),  "close": float(b.close), "volume": b.volume,
                } for b in bars])
                ind = compute_indicators(df)
                if not ind:
                    continue
                broker = get_broker()
                orderflow = await get_orderflow_score(ticker, broker)
                action, confidence, reasons = score_equity_signal(ind, orderflow_score=orderflow)

                trade_plan = {}
                if action in ("BUY", "SELL") and confidence >= settings.effective_equity_min_confidence:
                    trade_plan = compute_equity_trade_plan(
                        ind, action, portfolio_value=settings.starting_capital,
                    )

                signal = {
                    "id":              str(uuid.uuid4()),
                    "ticker":          ticker,
                    "asset_type":      "equity",
                    "generated_at":    datetime.now(timezone.utc).isoformat(),
                    "action":          action,
                    "confidence":      round(confidence, 4),
                    "orderflow_score": round(orderflow, 4),
                    "iv_overlay_boost": 0.0,
                    "earnings_gated":  False,
                    "reasons":         reasons,
                    "trade_plan":      trade_plan,
                    "indicators": {
                        "rsi":          ind.get("rsi"),
                        "macd":         ind.get("macd"),
                        "bb_pct_b":     ind.get("bb_pct_b"),
                        "atr":          ind.get("atr"),
                        "volume_ratio": ind.get("volume_ratio"),
                    },
                }
                _recent_signals.insert(0, signal)
                logger.info("Equity scan: %s → %s (conf=%.2f)", ticker, action, confidence)

                # Collect actionable signals; rank + route after the loop so the
                # highest-quality opportunities reach the frequency controller first.
                if action in ("BUY", "SELL") and confidence >= settings.effective_equity_min_confidence:
                    routable.append(signal)

            except Exception as exc:
                logger.warning("Equity scan failed for %s: %s", ticker, exc)

        # Rank by weighted quality score, then route highest-first. The frequency
        # controller inside handle_signal enforces the per-mode daily cap, so once
        # capacity is reached the lower-ranked signals are blocked, not the best.
        if routable:
            from app.services.trade_frequency_controller import trade_frequency_controller
            from app.api.routes.trade_desk import handle_signal
            for sig in trade_frequency_controller.rank(routable):
                try:
                    await handle_signal(sig)
                except Exception as exec_exc:
                    logger.warning("Execution handler failed for %s: %s",
                                   sig.get("ticker"), exec_exc)

        del _recent_signals[200:]   # keep last 200 only

    except Exception as exc:
        logger.warning("Background equity scan failed: %s", exc)


async def _live_spread_quote(
    broker, symbol: str, expiry_iso: str,
    short_strike: float, long_strike: float, opt_type: str,
) -> Optional[dict]:
    """
    Price a vertical spread off the LIVE options chain (real NBBO mids).

    Returns a dict with per-contract ``net_credit`` (dollars), the actual
    available strikes nearest the requested ones, and the short-leg delta — or
    ``None`` when a live chain / valid quotes are not available (e.g. no IBKR
    options market-data subscription), in which case the caller falls back to the
    Black-Scholes estimate.

    Using the real chain means the submitted limit price tracks where the spread
    can actually fill, instead of a theoretical Black-Scholes mid.
    """
    try:
        chain = await broker.get_options_chain(symbol, expiry_iso)
    except Exception as exc:
        logger.debug("Live options chain unavailable for %s %s: %s", symbol, expiry_iso, exc)
        return None

    legs = chain.puts if opt_type == "put" else chain.calls
    if not legs:
        return None

    def _nearest(target: float):
        return min(legs, key=lambda c: abs(float(c.strike) - target))

    short_c = _nearest(short_strike)
    long_c = _nearest(long_strike)
    if float(short_c.strike) == float(long_c.strike):
        return None  # chain too sparse to form the spread

    def _mid(c) -> Optional[float]:
        bid = float(c.bid or 0)
        ask = float(c.ask or 0)
        if bid > 0 and ask > 0 and ask >= bid:
            return (bid + ask) / 2.0
        last = float(getattr(c, "last", 0) or 0)
        return last if last > 0 else None

    short_mid = _mid(short_c)
    long_mid = _mid(long_c)
    if short_mid is None or long_mid is None:
        return None

    net_credit_ps = short_mid - long_mid
    if net_credit_ps <= 0:
        return None  # not a credit at these strikes — let BS / strike selection handle it

    short_delta = abs(float(short_c.greeks.delta)) if short_c.greeks and short_c.greeks.delta else None
    return {
        "net_credit":   round(net_credit_ps * 100, 2),
        "short_delta":  short_delta,
        "short_strike": float(short_c.strike),
        "long_strike":  float(long_c.strike),
    }


async def _yf_options_quote(
    symbol: str, target_expiry_iso: str,
    short_strike: float, long_strike: float, opt_type: str,
) -> Optional[dict]:
    """
    Price a vertical spread off yfinance's (free, ~15-min delayed) option chain.

    Used as the no-cost fallback when the broker chain has no quotes (IBKR without
    an options market-data subscription). Snaps to the nearest listed expiration and
    strikes, and prices each leg at its bid/ask mid (last price if bid/ask missing).
    yfinance does not provide greeks, so short_delta is left None and the caller
    keeps its Black-Scholes delta estimate. Returns None if no usable credit quote.
    """
    import asyncio
    loop = asyncio.get_running_loop()

    def _fetch() -> Optional[dict]:
        try:
            import yfinance as yf
            from datetime import date as _date
            tk = yf.Ticker(symbol)
            expirations = list(tk.options or [])
            if not expirations:
                return None
            target = _date.fromisoformat(target_expiry_iso)
            chosen = min(expirations,
                         key=lambda e: abs((_date.fromisoformat(e) - target).days))
            chain = tk.option_chain(chosen)
            df = chain.puts if opt_type == "put" else chain.calls
            if df is None or df.empty:
                return None

            def _leg(strike: float):
                idx = (df["strike"] - strike).abs().idxmin()
                row = df.loc[idx]
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                last = float(row.get("lastPrice", 0) or 0)
                if bid > 0 and ask > 0 and ask >= bid:
                    mid = (bid + ask) / 2.0
                elif last > 0:
                    mid = last
                else:
                    mid = None
                return float(row["strike"]), mid

            s_strike, s_mid = _leg(short_strike)
            l_strike, l_mid = _leg(long_strike)
            if s_mid is None or l_mid is None or s_strike == l_strike:
                return None
            net = s_mid - l_mid
            if net <= 0:
                return None
            return {
                "net_credit":   round(net * 100, 2),
                "short_delta":  None,
                "short_strike": s_strike,
                "long_strike":  l_strike,
                "expiration":   chosen,
            }
        except Exception:
            return None

    return await loop.run_in_executor(None, _fetch)


async def _run_options_scan() -> None:
    """
    Generate options spread signals based on current regime and SPY bars.
    Uses Black-Scholes to select ~0.30 delta short strike, 5pt wide spread, then
    prices the spread off the live IBKR chain when available (Black-Scholes mid is
    the fallback when there is no options market-data subscription).
    Routes through execution handler (manual/copilot/autopilot).
    """
    if _current_regime is None or not getattr(_current_regime, "options_allowed", False):
        return
    try:
        import uuid, calendar as _cal
        import numpy as np
        from datetime import datetime, timezone, timedelta, date
        from decimal import Decimal
        from app.broker.broker_factory import get_broker
        from app.services.options_pricer import BlackScholesPricer
        from app.services.trading_mode import trading_mode_manager

        pricer   = BlackScholesPricer()
        strategy = (_current_regime.strategies_allowed or ["bull_put_spread"])[0]
        dte_target = trading_mode_manager.config.dte_target or 30
        RISK_FREE  = 0.05

        # Get SPY bars via yfinance — no broker subscription needed
        spy_bars = await _yf_bars("SPY", limit=30)
        if len(spy_bars) < 20:
            return

        closes  = [float(b.close) for b in spy_bars]
        spot    = closes[-1]
        log_rets = np.diff(np.log(closes))
        sigma   = float(np.std(log_rets) * np.sqrt(252))
        vix_est = _current_regime.features_used.vix / 100.0 if _current_regime.features_used else sigma

        # Target expiry ~dte_target days out, on a Friday
        today       = date.today()
        target_exp  = today + timedelta(days=dte_target)
        while target_exp.weekday() != 4:   # roll to Friday
            target_exp += timedelta(days=1)
        T = max((target_exp - today).days / 365, 0.01)

        # Select short strike nearest 0.30 delta, long strike 5 pts away
        opt_type   = "put"  if "put" in strategy  else "call"
        is_call    = opt_type == "call"
        target_delta = 0.30

        best_short, best_delta_diff = spot, 1.0
        best_short_delta = target_delta
        for offset in range(-60, 61, 5):
            s = round(spot + offset)
            try:
                d = pricer.delta(spot, s, T, RISK_FREE, vix_est, opt_type)
                d_abs = abs(d)
                if abs(d_abs - target_delta) < best_delta_diff:
                    best_delta_diff = abs(d_abs - target_delta)
                    best_short = s
                    best_short_delta = d_abs
            except Exception:
                continue

        short_strike = float(best_short)
        long_strike  = short_strike - 5.0 if not is_call else short_strike + 5.0
        spread_width = abs(short_strike - long_strike)

        # Black-Scholes estimate (fallback / no-subscription path)
        try:
            short_px = pricer.put_price(spot, short_strike, T, RISK_FREE, vix_est) if not is_call \
                       else pricer.call_price(spot, short_strike, T, RISK_FREE, vix_est)
            long_px  = pricer.put_price(spot, long_strike,  T, RISK_FREE, vix_est) if not is_call \
                       else pricer.call_price(spot, long_strike,  T, RISK_FREE, vix_est)
            net_credit = round((short_px - long_px) * 100, 2)  # per contract $
        except Exception:
            net_credit = 0.0

        # Prefer the LIVE chain price when a quote is available — the limit then
        # tracks where the spread can actually fill instead of a theoretical mid.
        credit_source = "black_scholes"
        broker = get_broker()
        live = await _live_spread_quote(
            broker, "SPY", target_exp.isoformat(), short_strike, long_strike, opt_type,
        )
        if live and live["net_credit"] > 0:
            short_strike = live["short_strike"]
            long_strike  = live["long_strike"]
            spread_width = abs(short_strike - long_strike)
            net_credit   = live["net_credit"]
            if live["short_delta"] is not None:
                best_short_delta = live["short_delta"]
            credit_source = "live_chain"
        else:
            # Free fallback: price off yfinance's (delayed) option chain before
            # falling back to the Black-Scholes theoretical mid.
            yq = await _yf_options_quote(
                "SPY", target_exp.isoformat(), short_strike, long_strike, opt_type,
            )
            if yq and yq["net_credit"] > 0:
                short_strike = yq["short_strike"]
                long_strike  = yq["long_strike"]
                spread_width = abs(short_strike - long_strike)
                net_credit   = yq["net_credit"]
                target_exp   = date.fromisoformat(yq["expiration"])
                credit_source = "yfinance_chain"

        if spread_width <= 0 or net_credit <= 0:
            logger.info("Options scan: no usable spread (width=%.1f credit=%.2f) — skipping",
                        spread_width, net_credit)
            return

        credit_per_share = net_credit / 100.0
        max_loss_dollars = round((spread_width - credit_per_share) * 100, 2)

        # ── AI signal scoring gate ──────────────────────────────────────────
        # Mirror the equity path: an options spread must pass the scorer before
        # it is routed to execution. Previously options bypassed the scorer with
        # signal_score=0, so every spread that the regime allowed was traded.
        global _signal_scorer
        if _signal_scorer is None:
            from app.services.signal_scorer import SignalScorer
            _signal_scorer = SignalScorer()
        from app.services.signal_scorer import SignalFeatures

        feat = _current_regime.features_used
        features = SignalFeatures(
            iv_rank=float(getattr(feat, "iv_rank", 0.0)) if feat else 0.0,
            iv_percentile=float(getattr(feat, "iv_percentile", 0.0)) if feat else 0.0,
            vix_level=float(getattr(feat, "vix", vix_est * 100)) if feat else vix_est * 100,
            spy_rsi_14=float(getattr(feat, "rsi_14", 50.0)) if feat else 50.0,
            spy_adx_14=float(getattr(feat, "adx_14", 20.0)) if feat else 20.0,
            spy_trend_direction=1.0 if (feat and getattr(feat, "spy_return_20d", 0.0) >= 0) else -1.0,
            days_to_expiry=float(dte_target),
            short_strike_delta=float(best_short_delta),
            spread_width=float(spread_width),
            credit_to_width_ratio=(credit_per_share / spread_width) if spread_width else 0.0,
            earnings_days_away=60.0,   # SPY (ETF) — no single-name earnings event
            spy_realized_vol_20d=float(sigma),
            iv_minus_rv=float(vix_est - sigma),
        )
        score_result = await _signal_scorer.score_async(features)
        signal_score = float(score_result.score)
        if not score_result.approved:
            logger.info(
                "Options signal rejected by AI scorer: SPY %s score=%.3f — %s",
                strategy, signal_score, score_result.rejection_reason,
            )
            return

        # ── Position sizing via RiskManager ─────────────────────────────────
        # Previously every spread was quantity=1. Size off portfolio value, the
        # spread's max loss, the active trading mode's risk-per-trade %, and the
        # regime's options size multiplier — same machinery the equity path uses.
        from app.services.risk_manager import RiskManager
        try:
            acct = await broker.get_account_summary()
            portfolio_value = float(acct.net_liquidation or settings.starting_capital)
        except Exception:
            portfolio_value = settings.starting_capital
        risk_pct  = trading_mode_manager.config.risk_per_trade_pct
        regime_mult = float(getattr(_current_regime, "options_size_multiplier", 1.0))
        # Volatility-based sizing: scale the regime budget inversely with vol so
        # dollar risk stays steady across calm/fearful tape (Batch C).
        from app.services.volatility_sizing import vol_adjusted_multiplier, describe as _vol_desc
        _vix_for_sizing = float(getattr(feat, "vix", vix_est * 100)) if feat else vix_est * 100
        _ivr_for_sizing = float(getattr(feat, "iv_rank", 30.0)) if feat else 30.0
        size_mult = vol_adjusted_multiplier(regime_mult, _ivr_for_sizing, _vix_for_sizing)
        logger.info("Vol sizing: %s → mult %.2f×%.2f=%.2f",
                    _vol_desc(_ivr_for_sizing, _vix_for_sizing)["stance"],
                    regime_mult, size_mult / max(regime_mult, 1e-9), size_mult)
        quantity  = RiskManager().calculate_position_size(
            portfolio_value=portfolio_value,
            max_loss_per_spread=max_loss_dollars,
            risk_pct=risk_pct,
            size_multiplier=size_mult,
        )
        if quantity <= 0:
            logger.info(
                "Options signal skipped — sized to 0 contracts "
                "(portfolio=$%.0f max_loss=$%.0f risk_pct=%.3f mult=%.2f)",
                portfolio_value, max_loss_dollars, risk_pct, size_mult,
            )
            return

        # ── Options Intelligence: real POP / EV / Kelly for this spread ─────────
        # Drives the frequency controller's quality filter with the true
        # probability of profit instead of a proxy.
        intel = None
        try:
            from app.services.options_intelligence import analyze_spread
            intel = analyze_spread(
                spot=spot, short_strike=short_strike, long_strike=long_strike,
                option_type=opt_type, dte=float(dte_target), iv=vix_est,
                credit_per_share=credit_per_share, r=RISK_FREE,
            )
        except Exception as _intel_exc:
            logger.debug("Options intelligence failed: %s", _intel_exc)

        signal = {
            "id":           str(uuid.uuid4()),
            "ticker":       "SPY",
            "asset_type":   "options",
            "strategy":     strategy,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "action":       "SELL_SPREAD",
            # Confidence = real probability of profit when available; the frequency
            # controller then computes EV = POP·reward − (1−POP) directly.
            "confidence":   round(intel.pop, 4) if intel else round(getattr(_current_regime, "confidence", 0.5), 4),
            "pop":          round(intel.pop, 4) if intel else None,
            "kelly_fraction": intel.kelly_fraction if intel else None,
            "intelligence": intel.as_dict() if intel else None,
            "signal_score": round(signal_score, 4),
            "quantity":     int(quantity),
            "iv_rank":      round(features.iv_rank, 2),
            "regime":       _current_regime.regime.value,
            "spread": {
                "option_type":   opt_type,
                "short_strike":  short_strike,
                "long_strike":   long_strike,
                "expiration":    target_exp.isoformat(),
                "dte":           dte_target,
                "net_credit":    net_credit,
                "max_loss":      max_loss_dollars,
                "breakeven":     round(short_strike - credit_per_share, 2) if not is_call
                                 else round(short_strike + credit_per_share, 2),
            },
            "sigma":         round(sigma, 4),
            "vix_used":      round(vix_est * 100, 1),
            "credit_source": credit_source,
        }

        logger.info(
            "Options signal: %s SPY %s %s/%s exp %s credit $%.2f (%s) score=%.3f qty=%d",
            strategy, opt_type, short_strike, long_strike, target_exp, net_credit,
            credit_source, signal_score, quantity,
        )

        from app.api.routes.trade_desk import handle_signal
        await handle_signal(signal)

    except Exception as exc:
        logger.warning("Options scan failed: %s", exc)


def _fill_after_entry(fill_time, entry_dt) -> bool:
    """True if an execution happened at/after the trade's entry (tz-safe)."""
    if fill_time is None or entry_dt is None:
        return True   # can't tell — don't exclude
    try:
        from datetime import timezone as _tz
        ft = fill_time if fill_time.tzinfo else fill_time.replace(tzinfo=_tz.utc)
        ed = entry_dt if entry_dt.tzinfo else entry_dt.replace(tzinfo=_tz.utc)
        return ft >= ed
    except Exception:
        return True


def _compute_exit_price(fills: list, trade, is_equity: bool):
    """
    Reconstruct the per-share cost-to-close from real IBKR executions.

    Only counts the CLOSING-side fills that occurred at/after entry, weighted by
    shares — never averages the opening fill into the exit (the old bug). Returns
    None when the close cannot be reliably reconstructed, so the caller books an
    unknown P&L instead of a fabricated number.
    """
    if not fills:
        return None
    entry_dt = getattr(trade, "entry_date", None)

    def _wavg(rows) -> Optional[float]:
        sh = sum(r["shares"] for r in rows)
        if sh <= 0:
            return None
        return sum(r["price"] * r["shares"] for r in rows) / sh

    if is_equity:
        # Long closes with a SELL (SLD); short closes with a BUY (BOT).
        close_side = "BOT" if (trade.spread_type or "").lower() == "equity_short" else "SLD"
        rows = [
            f for f in fills
            if f["secType"] in ("STK", "") and f["side"] == close_side
            and _fill_after_entry(f["time"], entry_dt)
        ]
        px = _wavg(rows)
        return round(px, 4) if px is not None else None

    # Options credit spread: close = buy back the short leg + sell the long leg.
    # cost_to_close (per share, net debit) = short_buyback − long_sale.
    right = "C" if (trade.spread_type or "").lower().startswith("c") else "P"
    short_k = float(trade.short_strike or 0)
    long_k  = float(trade.long_strike or 0)

    def _leg(strike: float, side: str) -> Optional[float]:
        rows = [
            f for f in fills
            if f["secType"] == "OPT" and f["right"] == right
            and abs(f["strike"] - strike) < 0.01 and f["side"] == side
            and _fill_after_entry(f["time"], entry_dt)
        ]
        return _wavg(rows)

    short_close = _leg(short_k, "BOT")   # bought back the short leg
    long_close  = _leg(long_k, "SLD")    # sold the long leg
    if short_close is None or long_close is None:
        return None
    return round(short_close - long_close, 4)


async def _poll_fills() -> None:
    """
    Compare live broker positions against open DB trades.

    When a position disappears from IBKR (fully closed), reconstruct the actual
    cost-to-close from IBKR execution history and record the real P&L. If a real
    exit price cannot be determined, the trade is held open and retried for a
    grace window; only after that does it close with UNKNOWN P&L (never a
    fabricated $0), with a CRITICAL alert for manual reconciliation.
    """
    try:
        import asyncio
        from datetime import datetime, timezone
        from app.broker.broker_factory import get_broker
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from app.services.trade_recorder import trade_recorder
        from sqlalchemy import select

        broker = get_broker()
        live_positions = await broker.get_positions()

        # Build set of symbols currently held at IBKR
        live_symbols = {
            getattr(p, "symbol", getattr(p, "underlying", "")).upper()
            for p in live_positions
        }

        # Load all open + pending trades from DB
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Trade).where(Trade.status.in_(["open", "pending"]))
            )
            all_trades = result.scalars().all()

        open_trades    = [t for t in all_trades if t.status == "open"]
        pending_trades = [t for t in all_trades if t.status == "pending"]

        if not open_trades and not pending_trades:
            _close_pending.clear()
            _fill_pending.clear()
            return

        # Fetch recent IBKR executions once — detailed per-fill records so we can
        # match the closing side / specific option legs (not a blind all-time avg).
        fills_by_symbol: dict[str, list] = {}
        try:
            ib = getattr(broker, "ib", None)
            if ib is not None:
                from ib_insync import ExecutionFilter
                fills = await asyncio.wait_for(
                    ib.reqExecutionsAsync(ExecutionFilter()),
                    timeout=5.0,
                )
                for fill in fills:
                    c  = fill.contract
                    ex = fill.execution
                    sym = (c.symbol or "").upper()
                    rec = {
                        "secType": c.secType or "",
                        "strike":  float(c.strike or 0),
                        "right":   (c.right or "").upper(),
                        "side":    (ex.side or "").upper(),   # BOT / SLD
                        "price":   float(ex.price or 0),
                        "shares":  abs(float(ex.shares or 0)),
                        "time":    getattr(ex, "time", None),
                    }
                    if sym and rec["shares"] > 0 and rec["price"] > 0:
                        fills_by_symbol.setdefault(sym, []).append(rec)
        except Exception as _exec_exc:
            logger.debug("Could not fetch IBKR executions: %s", _exec_exc)

        now = datetime.now(timezone.utc)

        # ── Entry-side reconciliation: resolve pending (working) orders ─────────
        # A pending trade is promoted to `open` once its position shows at the
        # broker (or a fill execution is found). If, after the grace window, there
        # is still no position and no fill, the order terminated unfilled (DAY
        # expiry / ProgramCancel) → cancel it so it never becomes a phantom.
        for trade in pending_trades:
            underlying = (trade.underlying or "").upper()
            tid = str(trade.id)
            if not underlying:
                continue
            filled = underlying in live_symbols or bool(fills_by_symbol.get(underlying))
            if filled:
                await trade_recorder.confirm_fill(trade_id=tid)
                _fill_pending.pop(tid, None)
                continue
            first_seen = _fill_pending.setdefault(tid, now)
            if (now - first_seen).total_seconds() >= FILL_GRACE_SECONDS:
                await trade_recorder.cancel_pending(
                    trade_id=tid, reason="order_unfilled_timeout",
                )
                _fill_pending.pop(tid, None)
        # Drop fill markers for trades no longer pending
        _pending_ids = {str(t.id) for t in pending_trades}
        for tid in list(_fill_pending.keys()):
            if tid not in _pending_ids:
                _fill_pending.pop(tid, None)

        still_missing: set[str] = set()

        for trade in open_trades:
            underlying = (trade.underlying or "").upper()
            tid = str(trade.id)
            if not underlying or underlying in live_symbols:
                _close_pending.pop(tid, None)
                continue  # still open at broker

            still_missing.add(tid)

            spread_type = (trade.spread_type or "").lower()
            is_equity   = (trade.strategy == "equity") or spread_type.startswith("equity")
            exit_price  = _compute_exit_price(fills_by_symbol.get(underlying), trade, is_equity)

            if exit_price is not None:
                await trade_recorder.record_exit(
                    trade_id=tid,
                    cost_to_close=exit_price,
                    exit_reason="position_closed_at_broker",
                )
                _close_pending.pop(tid, None)
                logger.info(
                    "Auto-closed %s (%s) — cost_to_close=%.4f source=ibkr_execution",
                    tid, underlying, exit_price,
                )
                continue

            # No reliable exit price yet — wait within the grace window before
            # booking unknown, in case the execution report arrives shortly.
            first_missing = _close_pending.setdefault(tid, now)
            elapsed = (now - first_missing).total_seconds()
            if elapsed < CLOSE_GRACE_SECONDS:
                logger.warning(
                    "Position %s (%s) gone from broker but no execution price yet "
                    "— holding open, will retry (%.0fs/%ds elapsed)",
                    tid, underlying, elapsed, CLOSE_GRACE_SECONDS,
                )
                continue

            await trade_recorder.record_close_unknown(
                trade_id=tid,
                exit_reason="closed_price_unavailable",
            )
            _close_pending.pop(tid, None)

        # Drop pending markers for trades that are no longer missing/open
        for tid in list(_close_pending.keys()):
            if tid not in still_missing:
                _close_pending.pop(tid, None)

    except Exception as exc:
        logger.debug("_poll_fills: %s", exc)  # non-fatal


async def _update_portfolio_greeks() -> None:
    global _greeks_tracker
    if _greeks_tracker is None:
        return
    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()
        positions = await broker.get_positions()

        # Rebuild the tracker from live positions on every tick
        _greeks_tracker._positions.clear()
        for pos in positions:
            # Equities carry a placeholder option_type="call" and strike=0 from the
            # broker client, so option_type alone misclassifies them as options
            # (with zero Greeks). Use the strike==0 sentinel to detect equities.
            is_option = bool(getattr(pos, "option_type", None)) and float(getattr(pos, "strike", 0) or 0) != 0
            if is_option:
                # Options position — use broker-supplied Greeks if available
                greeks = getattr(pos, "greeks", None)
                _greeks_tracker.add_options_position(
                    symbol=pos.symbol,
                    qty=abs(pos.quantity),
                    side="short" if pos.quantity < 0 else "long",
                    delta=float(greeks.delta) if greeks else 0.0,
                    vega=float(greeks.vega) if greeks else 0.0,
                    theta=float(greeks.theta) if greeks else 0.0,
                )
            else:
                # Equity position
                _greeks_tracker.add_equity_position(
                    ticker=getattr(pos, "symbol", getattr(pos, "underlying", "?")),
                    qty=abs(pos.quantity),
                    side="long" if pos.quantity > 0 else "short",
                )

        snap = _greeks_tracker.snapshot()
        logger.debug(
            "Portfolio Greeks: delta=%+.4f vega=%+.4f theta=%+.4f positions=%d",
            snap["net_delta"], snap["net_vega"], snap["net_theta"], snap["total_position_count"],
        )
    except Exception as exc:
        logger.warning("Greeks update failed: %s", exc)


# ── Health check ────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """Returns 200 OK when the service is up."""
    return {"status": "ok", "broker": settings.broker}


@app.get("/api/health/detail", tags=["System"])
async def health_detail() -> dict:
    """
    Lightweight operational snapshot: scanner heartbeat, kill-switch state, the
    current regime, and the in-process observability counters / recent events.
    No external dependencies — safe to poll.
    """
    import time as _t
    from app.services.observability import observability
    from app.services.kill_switch import kill_switch_service as _ks

    age = (_t.monotonic() - _scheduler_last_tick) if _scheduler_last_tick else None
    scanner_ok = age is not None and age < 90
    return {
        "status": "ok",
        "broker": settings.broker,
        "scanner": {
            "alive": scanner_ok,
            "last_tick_age_seconds": round(age, 1) if age is not None else None,
        },
        "kill_switch": {"engaged": _ks.is_engaged, "reason": _ks.status.get("reason")},
        "regime": getattr(getattr(_current_regime, "regime", None), "value", None),
        "observability": observability.snapshot(),
    }


# ── Guardrail endpoints ─────────────────────────────────────────────────────
from app.services.guardrails import GuardrailEngine, PortfolioState

_guardrail_engine = GuardrailEngine()


@app.get("/api/guardrails/status", tags=["Guardrails"])
async def guardrail_status():
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from sqlalchemy import select, func, and_
    from datetime import date, timedelta

    # Read real P&L from DB
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    try:
        async with AsyncSessionLocal() as session:
            def _pnl_window(from_date):
                return select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) >= from_date)
                )
            daily_pnl   = float((await session.execute(_pnl_window(today))).scalar() or 0)
            weekly_pnl  = float((await session.execute(_pnl_window(week_start))).scalar() or 0)
            monthly_pnl = float((await session.execute(_pnl_window(month_start))).scalar() or 0)
            # Count trades ENTERED today (matches the daily-cap semantic used in
            # trade_desk._fetch_portfolio_state), regardless of open/closed status.
            trades_today = int((await session.execute(
                select(func.count(Trade.id)).where(
                    func.date(Trade.entry_date) == today
                )
            )).scalar() or 0)
            recent = (await session.execute(
                select(Trade.pnl).where(Trade.status == "closed")
                .order_by(Trade.exit_date.desc()).limit(10)
            )).scalars().all()
            consecutive_losses = 0
            for p in recent:
                if (p or 0) < 0: consecutive_losses += 1
                else: break
    except Exception:
        daily_pnl = weekly_pnl = monthly_pnl = 0.0
        trades_today = consecutive_losses = 0

    # Get real broker account value
    try:
        from app.broker.broker_factory import get_broker
        acct = await get_broker().get_account_summary()
        current_value = float(acct.net_liquidation)
    except Exception:
        current_value = settings.starting_capital

    portfolio = PortfolioState(
        current_value=current_value,
        starting_capital=settings.starting_capital,
        daily_pnl=daily_pnl,
        weekly_pnl=weekly_pnl,
        monthly_pnl=monthly_pnl,
        consecutive_losses=consecutive_losses,
        trades_today=trades_today,
    )
    status = _guardrail_engine.check_all(portfolio)

    return {
        "trading_allowed":       status.trading_allowed,
        "trading_mode":          status.trading_mode,
        "reason":                status.reason,
        "flags":                 status.flags,
        "daily_pnl":             daily_pnl,
        "weekly_pnl":            weekly_pnl,
        "monthly_pnl":           monthly_pnl,
        "daily_loss_pct":        status.daily_loss_pct,
        "weekly_loss_pct":       status.weekly_loss_pct,
        "monthly_loss_pct":      status.monthly_loss_pct,
        "consecutive_losses":    consecutive_losses,
        "trades_today":          trades_today,
        "capital_pct_remaining": status.capital_pct_remaining,
    }


@app.get("/api/guardrails/history", tags=["Guardrails"])
async def guardrail_history():
    return {"events": []}


@app.get("/api/guardrails/trading-mode", tags=["Guardrails"])
async def get_trading_mode():
    from app.services.trading_mode import trading_mode_manager
    return {"mode": trading_mode_manager.current.active_mode.value, "signal_threshold": settings.signal_score_threshold}


# ── Executive Summary (Dashboard header) ────────────────────────────────────
@app.get("/api/dashboard/summary", tags=["Dashboard"])
async def dashboard_summary():
    """
    Aggregated header for the Executive Summary panel: total equity, total P&L,
    day P&L, and a System Health checklist (broker, DB, agent, market hours,
    kill switch, config) with an issue count.
    """
    import time as _t
    from datetime import date as _date
    from sqlalchemy import select, func, and_
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.execution_mode import execution_mode_manager
    from app.services.kill_switch import kill_switch_service
    from app.utils.market_hours import market_status

    cap = float(settings.starting_capital)

    # ── P&L from DB (known-pnl closed trades only) ──────────────────────────
    total_pnl = day_pnl = 0.0
    db_ok = True
    try:
        today = _date.today()
        async with AsyncSessionLocal() as s:
            total_pnl = float((await s.execute(
                select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                    Trade.status == "closed", Trade.pnl.isnot(None))
            )).scalar() or 0)
            day_pnl = float((await s.execute(
                select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                    and_(Trade.status == "closed", Trade.pnl.isnot(None),
                         func.date(Trade.exit_date) == today))
            )).scalar() or 0)
    except Exception:
        db_ok = False

    # ── Equity from broker (fall back to capital + realized P&L) ────────────
    total_equity = cap + total_pnl
    broker_ok = False
    broker_detail = "Disconnected"
    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()
        ib = getattr(broker, "ib", None)
        broker_ok = bool(getattr(broker, "_connected", False)) and bool(ib.isConnected()) if ib else False
        if broker_ok:
            acct = await broker.get_account_summary()
            nl = float(acct.net_liquidation or 0)
            if nl > 0:
                total_equity = nl
            paper = settings.ibkr_trading_mode.lower() != "live"
            broker_detail = f"Connected — account {'PAPER' if paper else 'LIVE'}"
    except Exception:
        broker_ok = False

    # ── Background agent heartbeat ──────────────────────────────────────────
    agent_ok = bool(_scheduler_last_tick) and (_t.monotonic() - _scheduler_last_tick) < 90
    exec_mode = execution_mode_manager.mode.value

    mkt = market_status()
    ks_engaged = kill_switch_service.is_engaged
    gate_on = getattr(settings, "market_hours_only", True)

    health = [
        {"name": "IBKR Gateway", "status": "ok" if broker_ok else "error",
         "detail": broker_detail},
        {"name": "PostgreSQL", "status": "ok" if db_ok else "error",
         "detail": "Connected" if db_ok else "Unreachable"},
        {"name": "Trading Agent", "status": "ok" if agent_ok else "warn",
         "detail": f"Running — {exec_mode}" if agent_ok else "Not ticking"},
        {"name": "Market Hours", "status": "ok" if mkt["is_open"] else "warn",
         "detail": "Market open" if mkt["is_open"] else f"Market closed ({mkt['reason']})"},
        {"name": "Kill Switch",
         "status": "error" if ks_engaged else "ok",
         "detail": "ENGAGED — trading halted" if ks_engaged else "Disarmed"},
        {"name": "Config", "status": "ok",
         "detail": f"Mode {exec_mode} · market-hours gate {'on' if gate_on else 'off'} "
                   f"· RoR threshold {settings.signal_score_threshold}"},
    ]
    issues = sum(1 for h in health if h["status"] != "ok")

    return {
        "total_equity":  round(total_equity, 2),
        "total_pnl":     round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / cap * 100, 2) if cap else 0.0,
        "day_pnl":       round(day_pnl, 2),
        "day_pnl_pct":   round(day_pnl / cap * 100, 2) if cap else 0.0,
        "health":        health,
        "issues":        issues,
    }
