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
        import math as _math
        for ts, row in hist.iterrows():
            # Skip rows with missing/invalid OHLC. yfinance often returns the
            # current in-progress (or after-hours/weekend) bar with NaN prices;
            # building a Bar from it raised 4 validation errors and — unhandled —
            # killed the entire scan. Skip bad rows so the scan stays resilient.
            try:
                o = float(row["Open"]); h = float(row["High"])
                lo = float(row["Low"]); c = float(row["Close"])
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
from app.api.routes import options_flow
from app.api.routes import income_matrix
from app.api.routes import portfolio
from app.api.routes import options_csp
from app.api.routes import options_decision
from app.api.routes import intel
from app.api.routes import chart
from app.api.routes import alerts
from app.api.routes import ibkr_live
from app.core.config import settings

logger = get_logger(__name__)

app = FastAPI(
    title="OlbosTrade",
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
# wait this long (measured from trade.entry_date, not process uptime -- a
# restart must never reset this clock) for it to fill. After the window, an
# order with no broker position and no fill execution is treated as
# terminated-unfilled and the pending trade is cancelled (so unfilled/
# ProgramCancelled limit orders never become phantom positions, or worse,
# indefinitely block the duplicate-open guard for that underlying). Generous
# because DAY limit orders can sit unfilled.
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
app.include_router(options_flow.router, prefix="/api/options-flow", tags=["Options Flow"])
app.include_router(income_matrix.router, prefix="/api/income-matrix", tags=["Income Matrix"])
app.include_router(research.router,    prefix="/api/research",     tags=["Research"])
app.include_router(journal.router,     prefix="/api/journal",      tags=["Journal"])
app.include_router(analytics.router,   prefix="/api/analytics",    tags=["Analytics"])
app.include_router(trading_mode.router,prefix="/api/mode",         tags=["Trading Mode"])
app.include_router(equity.router,      prefix="/api/equity",       tags=["Equity"])
app.include_router(trade_desk.router,  prefix="/api/trade-desk",   tags=["Trade Desk"])
app.include_router(symphony.router,    prefix="/api/symphony",     tags=["Symphony"])
app.include_router(options.router,     prefix="/api/options",      tags=["Options"])
app.include_router(portfolio.router,   prefix="/api/portfolio",    tags=["Portfolio"])
app.include_router(options_csp.router, prefix="/api/options/csp",   tags=["Options Income"])
app.include_router(options_decision.router, prefix="/api/options-decision", tags=["Options Decision"])
app.include_router(intel.router,       prefix="/api/intel",        tags=["Intelligence Hub"])
app.include_router(chart.router,       prefix="/api/chart",        tags=["Chart Intelligence"])
app.include_router(alerts.router,      prefix="/api/alerts",       tags=["Smart Alerts"])
app.include_router(alerts.notif_router,prefix="/api/notifications",tags=["Notifications"])
app.include_router(ibkr_live.router,   prefix="/api/ibkr",         tags=["IBKR Live Data"])


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

        # Account mode guard — log loudly at startup if the gateway's real account
        # doesn't match IBKR_TRADING_MODE (e.g. configured paper but logged into a
        # live account). Execution is independently fail-closed per order; this is
        # the early-warning surface.
        try:
            from app.services.account_guard import verify_account_mode
            ok, detail = await verify_account_mode(broker)
            if ok:
                logger.info("Account mode verified — %s", detail)
            else:
                logger.critical("ACCOUNT MODE GUARD: %s — execution will be blocked", detail)
        except Exception as ag_exc:
            logger.warning("Account mode verification skipped: %s", ag_exc)
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

    if settings.execution_test_mode:
        logger.warning(
            "⚠ EXECUTION_TEST_MODE is ON — quality/frequency guards bypassed; the "
            "system will trade freely (PAPER validation). Disable for real runs."
        )

    # 4. Start background scheduler
    asyncio.create_task(_background_scheduler())

    # 4b. Intelligence Hub — register free news/filing/macro providers + seed
    # default smart watchlists (idempotent, non-fatal).
    try:
        from app.services.intel.bootstrap import register_default_providers
        from app.services.intel.watchlist_service import seed_defaults
        register_default_providers()
        await seed_defaults()
    except Exception as exc:
        logger.warning("Intel init skipped (non-fatal): %s", exc)

    # Initialize IBKR Live Data WebSocket broker (real-time quotes for scan panels)
    try:
        await ibkr_live.startup_ibkr_live()
    except Exception as exc:
        logger.warning("IBKR Live data broker init skipped (non-fatal): %s", exc)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Cleanup the IBKR Live Data broker on shutdown."""
    try:
        await ibkr_live.shutdown_ibkr_live()
    except Exception as exc:
        logger.warning("IBKR Live data broker shutdown failed: %s", exc)


async def _guarded(coro, name: str, timeout: float) -> None:
    """
    Run a scheduler sub-task with a hard timeout. A hung broker/IO call (e.g. an
    IBKR request that never returns) must never freeze the whole scheduler — that
    stops the heartbeat and the Trading Agent shows "Not ticking". On timeout or
    error we log and move on; the loop keeps ticking.
    """
    global _scheduler_last_tick
    import time as _t
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error("Scheduler task '%s' timed out after %.0fs — skipped", name, timeout)
    except Exception as exc:
        logger.error("Scheduler task '%s' failed: %s", name, exc)
    finally:
        # Refresh the heartbeat after each sub-task so a legitimately slow scan
        # can't make the agent look stalled.
        _scheduler_last_tick = _t.monotonic()


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
                        await asyncio.wait_for(_broker.connect(), timeout=30)
                        logger.info("Broker reconnected successfully")
                except Exception as _rc_exc:
                    logger.warning("Broker reconnect failed: %s", _rc_exc)
                last_reconnect = now

            # Every 30 min: regime reclassify
            if now - last_regime >= regime_interval_s:
                await _guarded(_reclassify_regime(), "regime", 45)
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
                    await _guarded(_run_equity_scan(), "equity_scan", 90)
                else:
                    logger.info(
                        "Equity scan skipped — regime %s does not allow equities",
                        getattr(_current_regime, "regime_type", "unknown"),
                    )
                last_equity = now

            # Every 1 hour: options spread signal scan (if regime allows).
            # SPY and QQQ both scanned each cycle — see _run_options_scan's
            # docstring for why QQQ reuses SPY's regime as a shared proxy.
            if now - last_options >= options_interval_s:
                for _opt_symbol in ("SPY", "QQQ"):
                    await _guarded(
                        _run_options_scan(_opt_symbol),
                        f"options_scan_{_opt_symbol.lower()}", 90,
                    )
                last_options = now

            # Every 30 sec: poll fills from active broker
            if now - last_fills >= fills_interval_s:
                await _guarded(_poll_fills(), "poll_fills", 20)
                last_fills = now

            # Every 1 min: update portfolio Greeks
            if now - last_greeks >= greeks_interval_s:
                await _guarded(_update_portfolio_greeks(), "greeks", 30)
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
        from app.services.account_state import get_account_value
        from app.api.routes.equity import _recent_signals   # shared in-memory store

        watchlist = settings.get_equity_watchlist()
        routable: list = []   # qualifying signals to rank + route highest-first
        # One live account fetch per scan cycle, not per-ticker.
        account_value = await get_account_value()

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

                # Test mode routes any BUY/SELL regardless of confidence so the
                # pipeline actually trades for validation.
                routable_signal = action in ("BUY", "SELL") and (
                    settings.execution_test_mode
                    or confidence >= settings.effective_equity_min_confidence
                )

                trade_plan = {}
                if routable_signal:
                    trade_plan = compute_equity_trade_plan(
                        ind, action, portfolio_value=account_value,
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
                if routable_signal:
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


async def _build_portfolio_risk_state(portfolio_value: float):
    """
    Real PortfolioRiskState for RiskManager.approve_trade()'s concentration
    check — positions_by_underlying/positions_by_sector grouped from actual
    open trades via portfolio_engine.position_risk_dollars()/sector_for()
    (the same logic /api/portfolio/heat uses), net Greeks from the live
    _greeks_tracker when available. SPY and QQQ both map to sector "Index"
    (see portfolio_engine.SECTORS), so trading both is correctly seen as one
    correlated bucket rather than two independent 25%-cap slots.
    """
    from app.services.risk_manager import PortfolioRiskState
    from app.services.portfolio_engine import position_risk_dollars, sector_for
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from sqlalchemy import select

    by_underlying: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    open_count = 0
    try:
        async with AsyncSessionLocal() as session:
            open_trades = (await session.execute(
                select(Trade).where(Trade.status == "open")
            )).scalars().all()
        open_count = len(open_trades)
        for t in open_trades:
            u = (t.underlying or "?").upper()
            s = sector_for(u)
            r = position_risk_dollars(t)
            by_underlying[u] = by_underlying.get(u, 0.0) + r
            by_sector[s] = by_sector.get(s, 0.0) + r
    except Exception as exc:
        logger.warning("Could not load open positions for concentration check: %s", exc)

    net_delta = net_vega = net_theta = 0.0
    if _greeks_tracker is not None:
        try:
            net_delta = _greeks_tracker.net_delta()
            net_vega  = _greeks_tracker.net_vega()
            net_theta = _greeks_tracker.net_theta()
        except Exception:
            pass

    return PortfolioRiskState(
        net_delta=net_delta, net_vega=net_vega, net_theta=net_theta,
        open_position_count=open_count, portfolio_value=portfolio_value,
        positions_by_underlying=by_underlying, positions_by_sector=by_sector,
    )


async def _run_options_scan(symbol: str = "SPY") -> None:
    """
    Generate options spread signals for `symbol` based on the current regime.

    The regime itself is still classified from SPY alone (_reclassify_regime) —
    scanning QQQ reuses that same regime/VIX/IV-rank state as a shared proxy
    rather than building QQQ its own classifier, since SPY and QQQ are highly
    correlated broad-market proxies. What IS symbol-specific: the underlying's
    own price bars/SMA/spot, its own option chain and quotes, and the
    concentration check below (positions_by_underlying/positions_by_sector —
    both SPY and QQQ fall under the same "Index" sector in portfolio_engine.py,
    so trading both can't silently double the correlated exposure past the
    sector cap).

    Delegates strike selection, entry-condition gating, and the credit-vs-debit
    distinction to the real per-strategy classes in strategy_engine.py — the
    same ones the backtester and ML training pipeline use. Previously this
    function used one generic "0.30-delta short, 5pt wide" credit-spread
    template for whichever strategy the regime picked, which: never re-checked
    a strategy's own entry conditions (IV rank/RSI/ADX/SMA) live, used the
    wrong delta/width for bull_put_spread and bear_call_spread (0.20delta/10pt
    in strategy_engine.py, not 0.30/5), and for bull_call_debit_spread built a
    call *credit* spread (sell near, buy far) while labeling it "SELL_SPREAD"
    — the opposite of what that strategy actually is (buy the ATM leg, sell an
    OTM leg, a net debit). LOW_VOL_TRENDING — a common, currently-active regime
    — allows *only* bull_call_debit_spread, so this was live, not theoretical.

    iron_condor is intentionally skipped: its two-sided put+call structure
    isn't wired into trade_desk._execute_signal's order construction (2 legs
    only), so submitting it would silently open just one side. No regime
    config currently lists it first anyway (see REGIME_CONFIG), so this is a
    documented gap, not an active one.

    Routes through execution handler (manual/copilot/autopilot), same as before.
    """
    if _current_regime is None or not getattr(_current_regime, "options_allowed", False):
        return
    try:
        import uuid
        import numpy as np
        from datetime import datetime, timezone, timedelta, date
        from decimal import Decimal
        from app.broker.broker_factory import get_broker
        from app.broker.broker_interface import OptionsChain, OptionContract, Greeks as GK
        from app.services.options_pricer import BlackScholesPricer
        from app.services.trading_mode import trading_mode_manager
        from app.services.strategy_engine import (
            BullPutSpread, BearCallSpread, IronCondor, BullCallDebitSpread,
        )
        from app.api.routes.trade_desk import _fetch_portfolio_state, RiskGateError

        strategy_name = (_current_regime.strategies_allowed or ["bull_put_spread"])[0]
        strategy_classes = {
            "bull_put_spread":        BullPutSpread,
            "bear_call_spread":       BearCallSpread,
            "iron_condor":            IronCondor,
            "bull_call_debit_spread": BullCallDebitSpread,
        }
        strategy_cls = strategy_classes.get(strategy_name)
        if strategy_cls is None:
            logger.warning("Options scan: unknown strategy %r — skipping", strategy_name)
            return
        if strategy_name == "iron_condor":
            logger.info(
                "Options scan: iron_condor isn't wired for live 2-sided order "
                "submission yet — skipping"
            )
            return
        strategy_obj = strategy_cls()
        is_debit = strategy_name == "bull_call_debit_spread"
        is_call  = strategy_name in ("bear_call_spread", "bull_call_debit_spread")
        opt_type = "call" if is_call else "put"

        pricer     = BlackScholesPricer()
        dte_target = trading_mode_manager.config.dte_target or 30
        RISK_FREE  = 0.05

        # Get the underlying's bars via yfinance — no broker subscription needed
        underlying_bars = await _yf_bars(symbol, limit=30)
        if len(underlying_bars) < 20:
            return

        closes = [float(b.close) for b in underlying_bars]
        spot   = closes[-1]
        sma20  = float(np.mean(closes[-20:]))
        above_sma20 = spot > sma20
        log_rets = np.diff(np.log(closes))
        sigma   = float(np.std(log_rets) * np.sqrt(252))

        feat    = _current_regime.features_used
        iv_rank = float(getattr(feat, "iv_rank", 30.0)) if feat else 30.0
        rsi     = float(getattr(feat, "rsi_14", 50.0)) if feat else 50.0
        adx     = float(getattr(feat, "adx_14", 20.0)) if feat else 20.0
        vix_pct = float(getattr(feat, "vix", sigma * 100)) if feat else sigma * 100
        vix_est = vix_pct / 100.0

        # Real, fail-closed portfolio state — generate_signal()'s own guardrail
        # check needs this; skip the cycle rather than trade on stale/unknown risk.
        try:
            portfolio_state = await _fetch_portfolio_state()
        except RiskGateError as exc:
            logger.warning("Options scan: risk gate unavailable — skipping cycle: %s", exc)
            return

        # Target expiry ~dte_target days out, on a Friday
        today      = date.today()
        target_exp = today + timedelta(days=dte_target)
        while target_exp.weekday() != 4:   # roll to Friday
            target_exp += timedelta(days=1)
        T = max((target_exp - today).days / 365, 0.01)

        # Synthetic strike-grid chain (Black-Scholes) — same construction the
        # backtester uses — so strategy_obj's own _find_strike_by_delta() picks
        # its own real target delta/strikes instead of a hardcoded 0.30/5pt.
        calls: list = []
        puts: list = []
        for offset in range(-60, 61, 5):
            s = float(round(spot + offset))
            try:
                put_px  = pricer.put_price(spot, s, T, RISK_FREE, vix_est)
                call_px = pricer.call_price(spot, s, T, RISK_FREE, vix_est)
                put_d   = pricer.delta(spot, s, T, RISK_FREE, vix_est, "put")
                call_d  = pricer.delta(spot, s, T, RISK_FREE, vix_est, "call")
                gamma_v = pricer.gamma(spot, s, T, RISK_FREE, vix_est)
                put_th  = pricer.theta(spot, s, T, RISK_FREE, vix_est, "put")
                call_th = pricer.theta(spot, s, T, RISK_FREE, vix_est, "call")
                vega_v  = pricer.vega(spot, s, T, RISK_FREE, vix_est)
            except Exception:
                continue
            half_spread = 0.05
            puts.append(OptionContract(
                symbol=f"{symbol}_P{int(s)}", underlying=symbol, expiration=target_exp,
                strike=Decimal(str(int(s))), option_type="put",
                bid=Decimal(str(round(max(put_px - half_spread, 0.01), 2))),
                ask=Decimal(str(round(put_px + half_spread, 2))),
                last=Decimal(str(round(put_px, 2))), volume=1000, open_interest=5000,
                greeks=GK(delta=put_d, gamma=gamma_v, theta=put_th, vega=vega_v, implied_vol=vix_est),
            ))
            calls.append(OptionContract(
                symbol=f"{symbol}_C{int(s)}", underlying=symbol, expiration=target_exp,
                strike=Decimal(str(int(s))), option_type="call",
                bid=Decimal(str(round(max(call_px - half_spread, 0.01), 2))),
                ask=Decimal(str(round(call_px + half_spread, 2))),
                last=Decimal(str(round(call_px, 2))), volume=1000, open_interest=5000,
                greeks=GK(delta=call_d, gamma=gamma_v, theta=call_th, vega=vega_v, implied_vol=vix_est),
            ))
        chain = OptionsChain(
            underlying=symbol, expiration=target_exp,
            underlying_price=Decimal(str(round(spot, 2))),
            calls=calls, puts=puts, fetched_at=datetime.now(timezone.utc),
        )

        signal_obj = strategy_obj.generate_signal(
            chain=chain, iv_rank=iv_rank, rsi=rsi, adx=adx,
            above_sma20=above_sma20, vix=vix_pct, portfolio_state=portfolio_state,
        )
        if not signal_obj.entry_allowed or not signal_obj.short_strike:
            logger.info("Options scan: %s entry not allowed — %s", strategy_name, signal_obj.reason)
            return

        short_strike = signal_obj.short_strike
        long_strike  = signal_obj.long_strike or (
            short_strike + 10.0 if is_call else short_strike - 10.0
        )
        spread_width = abs(short_strike - long_strike)
        best_short_delta = signal_obj.target_delta or 0.20

        # Black-Scholes price at the strategy's own chosen strikes (fallback / no-subscription path)
        # Net delta/vega (long leg minus short leg — the position is short the
        # short_strike leg, long the long_strike leg, uniformly across all 4
        # strategies) feed the portfolio-level concentration check below.
        try:
            short_px = pricer.call_price(spot, short_strike, T, RISK_FREE, vix_est) if is_call \
                       else pricer.put_price(spot, short_strike, T, RISK_FREE, vix_est)
            long_px  = pricer.call_price(spot, long_strike, T, RISK_FREE, vix_est) if is_call \
                       else pricer.put_price(spot, long_strike, T, RISK_FREE, vix_est)
            net_amount = round((short_px - long_px) * 100, 2)  # +credit / -debit, per contract $
            _greek_opt = "call" if is_call else "put"
            net_position_delta = (
                pricer.delta(spot, long_strike, T, RISK_FREE, vix_est, _greek_opt)
                - pricer.delta(spot, short_strike, T, RISK_FREE, vix_est, _greek_opt)
            )
            net_position_vega = (
                pricer.vega(spot, long_strike, T, RISK_FREE, vix_est)
                - pricer.vega(spot, short_strike, T, RISK_FREE, vix_est)
            )
        except Exception:
            net_amount = 0.0
            net_position_delta = net_position_vega = 0.0

        # Prefer the LIVE chain price when a quote is available — the limit then
        # tracks where the spread can actually fill instead of a theoretical mid.
        # Both fallback helpers reject non-positive "credit", which only holds
        # for the 3 credit strategies — bull_call_debit_spread stays on the
        # Black-Scholes estimate above instead of risking a sign mixup reusing
        # credit-only helpers for a debit trade.
        credit_source = "black_scholes"
        broker = get_broker()
        if not is_debit:
            live = await _live_spread_quote(
                broker, symbol, target_exp.isoformat(), short_strike, long_strike, opt_type,
            )
            if live and live["net_credit"] > 0:
                short_strike = live["short_strike"]
                long_strike  = live["long_strike"]
                spread_width = abs(short_strike - long_strike)
                net_amount   = live["net_credit"]
                if live["short_delta"] is not None:
                    best_short_delta = live["short_delta"]
                credit_source = "live_chain"
            else:
                yq = await _yf_options_quote(
                    symbol, target_exp.isoformat(), short_strike, long_strike, opt_type,
                )
                if yq and yq["net_credit"] > 0:
                    short_strike = yq["short_strike"]
                    long_strike  = yq["long_strike"]
                    spread_width = abs(short_strike - long_strike)
                    net_amount   = yq["net_credit"]
                    target_exp   = date.fromisoformat(yq["expiration"])
                    credit_source = "yfinance_chain"

        if spread_width <= 0:
            logger.info("Options scan: no usable spread width — skipping")
            return
        if is_debit:
            net_debit = -net_amount
            if net_debit <= 0.05:
                logger.info("Options scan: debit too small ($%.2f) — skipping", net_debit)
                return
        elif net_amount <= 0.05:
            logger.info("Options scan: no usable spread (width=%.1f credit=%.2f) — skipping",
                        spread_width, net_amount)
            return

        credit_per_share = net_amount / 100.0
        max_loss_dollars = (
            round(abs(net_amount), 2) if is_debit
            else round((spread_width - credit_per_share) * 100, 2)
        )

        # ── AI signal scoring gate ──────────────────────────────────────────
        # Mirror the equity path: an options spread must pass the scorer before
        # it is routed to execution. Previously options bypassed the scorer with
        # signal_score=0, so every spread that the regime allowed was traded.
        global _signal_scorer
        if _signal_scorer is None:
            from app.services.signal_scorer import SignalScorer
            _signal_scorer = SignalScorer()
        from app.services.signal_scorer import SignalFeatures

        features = SignalFeatures(
            iv_rank=iv_rank,
            iv_percentile=iv_rank,
            vix_level=vix_pct,
            spy_rsi_14=rsi,
            spy_adx_14=adx,
            spy_trend_direction=1.0 if above_sma20 else -1.0,
            days_to_expiry=float(dte_target),
            short_strike_delta=float(best_short_delta),
            spread_width=float(spread_width),
            credit_to_width_ratio=(net_amount / 100.0 / spread_width) if spread_width else 0.0,
            earnings_days_away=60.0,   # SPY/QQQ (ETFs) — no single-name earnings event
            spy_realized_vol_20d=float(sigma),
            iv_minus_rv=float(vix_est - sigma),
        )
        score_result = await _signal_scorer.score_async(features)
        signal_score = float(score_result.score)
        if not score_result.approved and not settings.execution_test_mode:
            logger.info(
                "Options signal rejected by AI scorer: %s %s score=%.3f — %s",
                symbol, strategy_name, signal_score, score_result.rejection_reason,
            )
            return
        if not score_result.approved:
            logger.warning(
                "EXECUTION_TEST_MODE: routing options signal %s %s despite AI score=%.3f",
                symbol, strategy_name, signal_score,
            )

        # ── Position sizing via RiskManager ─────────────────────────────────
        # Size off portfolio value, the spread's max loss, the active trading
        # mode's risk-per-trade %, and the regime's options size multiplier —
        # same machinery the equity path uses.
        from app.services.risk_manager import RiskManager
        from app.services.account_state import get_account_value
        portfolio_value = await get_account_value()
        risk_pct    = trading_mode_manager.config.risk_per_trade_pct
        regime_mult = float(getattr(_current_regime, "options_size_multiplier", 1.0))
        # Volatility-based sizing: scale the regime budget inversely with vol so
        # dollar risk stays steady across calm/fearful tape (Batch C).
        from app.services.volatility_sizing import vol_adjusted_multiplier, describe as _vol_desc
        size_mult = vol_adjusted_multiplier(regime_mult, iv_rank, vix_pct)
        logger.info("Vol sizing: %s → mult %.2f×%.2f=%.2f",
                    _vol_desc(iv_rank, vix_pct)["stance"],
                    regime_mult, size_mult / max(regime_mult, 1e-9), size_mult)
        quantity = RiskManager().calculate_position_size(
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

        # ── Single-underlying / sector concentration check ──────────────────
        # SPY and QQQ both map to sector "Index" (portfolio_engine.SECTORS),
        # so scanning both can't silently double correlated exposure past the
        # sector cap. Deliberately narrower than RiskManager.approve_trade():
        # that method also gates on portfolio delta/vega, but those limits
        # have never been checked against a real trade before (approve_trade
        # was never called from any live path) and a sanity check found a
        # standard single 10-point-wide spread already exceeds the vega cap
        # (0.15) on its own — a separate, pre-existing calibration issue, not
        # something to silently work around here. Only the concentration
        # logic is reused; net_position_delta/vega stay unused for now.
        from app.services.portfolio_engine import sector_for
        portfolio_risk = await _build_portfolio_risk_state(portfolio_value)
        trade_sector = sector_for(symbol)
        total_new_risk = max_loss_dollars * quantity
        if portfolio_risk.portfolio_value > 0:
            new_underlying_exposure = (
                portfolio_risk.positions_by_underlying.get(symbol, 0.0) + total_new_risk
            )
            underlying_pct = new_underlying_exposure / portfolio_risk.portfolio_value
            if underlying_pct > RiskManager.MAX_SINGLE_UNDERLYING:
                logger.info(
                    "Options signal blocked — %s concentration would be %.1f%% "
                    "of portfolio (max %.0f%%)",
                    symbol, underlying_pct * 100, RiskManager.MAX_SINGLE_UNDERLYING * 100,
                )
                return
            new_sector_exposure = (
                portfolio_risk.positions_by_sector.get(trade_sector, 0.0) + total_new_risk
            )
            sector_pct = new_sector_exposure / portfolio_risk.portfolio_value
            if sector_pct > RiskManager.MAX_SECTOR_CONCENTRATION:
                logger.info(
                    "Options signal blocked — sector %r (%s) concentration would be "
                    "%.1f%% of portfolio (max %.0f%%)",
                    trade_sector, symbol, sector_pct * 100, RiskManager.MAX_SECTOR_CONCENTRATION * 100,
                )
                return

        # ── Options Intelligence: real POP / EV / Kelly for this spread ─────────
        # Drives the frequency controller's quality filter with the true
        # probability of profit instead of a proxy. analyze_spread() clamps
        # credit_per_share to >= 0, so it isn't meaningful for a debit spread
        # (credit_per_share is negative there) — skip rather than feed it a
        # floored-to-zero credit and get a fabricated POP/Kelly back.
        intel = None
        if not is_debit:
            try:
                from app.services.options_intelligence import analyze_spread
                intel = analyze_spread(
                    spot=spot, short_strike=short_strike, long_strike=long_strike,
                    option_type=opt_type, dte=float(dte_target), iv=vix_est,
                    credit_per_share=credit_per_share, r=RISK_FREE,
                )
            except Exception as _intel_exc:
                logger.debug("Options intelligence failed: %s", _intel_exc)

        if is_debit:
            breakeven = round(long_strike - credit_per_share, 2)
        elif is_call:
            breakeven = round(short_strike + credit_per_share, 2)
        else:
            breakeven = round(short_strike - credit_per_share, 2)

        signal = {
            "id":           str(uuid.uuid4()),
            "ticker":       symbol,
            "asset_type":   "options",
            "strategy":     strategy_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "action":       "BUY_SPREAD" if is_debit else "SELL_SPREAD",
            # Confidence = real probability of profit when available; the frequency
            # controller then computes EV = POP·reward − (1−POP) directly.
            "confidence":   round(intel.pop, 4) if intel else round(getattr(_current_regime, "confidence", 0.5), 4),
            "pop":          round(intel.pop, 4) if intel else None,
            "kelly_fraction": intel.kelly_fraction if intel else None,
            "intelligence": intel.as_dict() if intel else None,
            "signal_score": round(signal_score, 4),
            "quantity":     int(quantity),
            "iv_rank":      round(iv_rank, 2),
            "regime":       _current_regime.regime.value,
            "spread": {
                "option_type":   opt_type,
                "short_strike":  short_strike,
                "long_strike":   long_strike,
                "expiration":    target_exp.isoformat(),
                "dte":           dte_target,
                # Signed: positive = net credit received, negative = net debit
                # paid. The broker layer (ibkr_client.place_order) and P&L
                # recording (trade_recorder.record_exit) already expect this
                # convention — see their docstrings.
                "net_credit":    round(net_amount, 2),
                "max_loss":      max_loss_dollars,
                "breakeven":     breakeven,
            },
            "sigma":         round(sigma, 4),
            "vix_used":      round(vix_est * 100, 1),
            "credit_source": credit_source,
        }

        logger.info(
            "Options signal: %s %s %s %s/%s exp %s %s $%.2f (%s) score=%.3f qty=%d",
            strategy_name, symbol, opt_type, short_strike, long_strike, target_exp,
            "debit" if is_debit else "credit", abs(net_amount), credit_source,
            signal_score, quantity,
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

        # Sum live unrealized P&L per underlying (for MFE/MAE excursion tracking).
        live_upnl: dict[str, float] = {}
        for p in live_positions:
            sym = getattr(p, "symbol", getattr(p, "underlying", "")).upper()
            upnl = getattr(p, "unrealized_pnl", None)
            if sym and upnl is not None:
                live_upnl[sym] = live_upnl.get(sym, 0.0) + float(upnl)

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
        #
        # The grace-period clock is derived from trade.entry_date (persisted),
        # not an in-memory "first seen" timestamp — a backend restart mid-grace
        # (e.g. a routine deploy) used to reset the in-memory clock, leaving a
        # stuck pending trade blocking the duplicate-open guard for up to
        # another full FILL_GRACE_SECONDS after the restart, on top of however
        # long it had already been stuck. Confirmed in production: an
        # unfilled NVDA bracket order stayed pending well past 30 minutes and
        # blocked every subsequent NVDA signal with "skipped: already_open"
        # because a deploy landed mid-grace-period and restarted its timer.
        for trade in pending_trades:
            underlying = (trade.underlying or "").upper()
            tid = str(trade.id)
            if not underlying:
                continue
            filled = underlying in live_symbols or bool(fills_by_symbol.get(underlying))
            if filled:
                await trade_recorder.confirm_fill(trade_id=tid)
                continue
            entry_dt = trade.entry_date
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            if (now - entry_dt).total_seconds() >= FILL_GRACE_SECONDS:
                await trade_recorder.cancel_pending(
                    trade_id=tid, reason="order_unfilled_timeout",
                )

        still_missing: set[str] = set()

        for trade in open_trades:
            underlying = (trade.underlying or "").upper()
            tid = str(trade.id)
            if not underlying or underlying in live_symbols:
                _close_pending.pop(tid, None)
                # Still open at broker — advance MFE/MAE from live unrealized P&L.
                if underlying in live_upnl:
                    await trade_recorder.update_excursion(
                        trade_id=tid, unrealized_pnl=live_upnl[underlying],
                    )
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
        from app.services.trade_excursion_tracker import trade_excursion_tracker
        broker = get_broker()
        positions = await broker.get_positions()

        excursion_result = await trade_excursion_tracker.update_from_broker_positions(positions)
        if excursion_result.updated_trades > 0:
            logger.debug(
                "Trade excursion tracker updated %d trade(s)",
                excursion_result.updated_trades,
            )

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
        "paper_mode":            settings.is_paper_trading,
        "paper_visibility_mode": settings.paper_visibility_active,
        "daily_pnl":             daily_pnl,
        "weekly_pnl":            weekly_pnl,
        "monthly_pnl":           monthly_pnl,
        "daily_loss_pct":        status.daily_loss_pct,
        "weekly_loss_pct":       status.weekly_loss_pct,
        "monthly_loss_pct":      status.monthly_loss_pct,
        "consecutive_losses":    consecutive_losses,
        "trades_today":          trades_today,
        "capital_pct_remaining": status.capital_pct_remaining,
        "max_daily_loss_pct":    _guardrail_engine.max_daily_loss_pct,
        "max_weekly_loss_pct":   _guardrail_engine.max_weekly_loss_pct,
        "max_monthly_loss_pct":  _guardrail_engine.max_monthly_loss_pct,
        "max_trades_per_day":    _guardrail_engine.max_trades_per_day,
        "max_consecutive_losses": _guardrail_engine.max_consecutive_losses,
        "capital_preservation_threshold": _guardrail_engine.preservation_threshold,
        "signal_threshold":      _guardrail_engine.get_signal_threshold(status),
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
        {"name": "Config",
         "status": "warn" if settings.execution_test_mode else "ok",
         "detail": (("⚠ TEST MODE (guards bypassed) · " if settings.execution_test_mode else "")
                    + f"Mode {exec_mode} · market-hours gate {'on' if gate_on else 'off'} "
                    + f"· RoR threshold {settings.signal_score_threshold}")},
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
