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
    Used by regime classifier and options scan instead of IBKR.
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
from app.api.routes import trade_desk
from app.api.routes import options_flow
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
app.include_router(trade_desk.router,  prefix="/api/trade-desk",   tags=["Trade Desk"])
app.include_router(options_flow.router,prefix="/api/options-flow",  tags=["Options Flow"])

# Nightly archive scheduler (Options Flow data retention)
_flow_scheduler: Optional[object] = None


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
        logger.info("Kill switch wired to broker")
    except Exception as exc:
        logger.warning("Broker initialization failed (non-fatal): %s", exc)

    # 2. Initialize portfolio Greeks tracker
    from app.services.portfolio_greeks import PortfolioGreeksTracker
    _greeks_tracker = PortfolioGreeksTracker()
    logger.info("PortfolioGreeksTracker initialized")

    # 3. Classify regime on startup
    async def _startup_market_init():
        await _reclassify_regime()
    asyncio.create_task(_startup_market_init())

    # 4. Start background scheduler
    asyncio.create_task(_background_scheduler())

    # 5. Start Options Flow ingest service (idle unless enabled / demo mode)
    try:
        from app.services.options_flow_ingest import options_flow_ingest
        await options_flow_ingest.start()
    except Exception as exc:
        logger.warning("Options flow ingest failed to start (non-fatal): %s", exc)

    # 6. Nightly options_flow archive job (data retention → JSONL)
    global _flow_scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.services.options_flow_ingest import archive_old_flow

        _flow_scheduler = AsyncIOScheduler(timezone="America/New_York")
        _flow_scheduler.add_job(
            archive_old_flow, "cron", hour=2, minute=0, id="options_flow_archive"
        )
        _flow_scheduler.start()
        logger.info("Options flow archive job scheduled (nightly 02:00 ET)")
    except Exception as exc:
        logger.warning("Options flow archive scheduler failed: %s", exc)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Cleanly stop the ingest service, archive scheduler, and Redis client."""
    try:
        from app.services.options_flow_ingest import options_flow_ingest
        await options_flow_ingest.stop()
    except Exception as exc:
        logger.debug("Options flow ingest stop error: %s", exc)
    global _flow_scheduler
    if _flow_scheduler is not None:
        try:
            _flow_scheduler.shutdown(wait=False)
        except Exception:
            pass
        _flow_scheduler = None
    try:
        from app.core.redis import close_redis
        await close_redis()
    except Exception:
        pass


async def _background_scheduler() -> None:
    """Background task that runs periodic scans and updates."""
    global _current_regime

    options_interval_s = 30 * 60   # 30 minutes
    regime_interval_s  = 30 * 60   # 30 minutes
    greeks_interval_s  = 60        # 1 minute
    fills_interval_s   = 30        # 30 seconds
    exit_interval_s    = settings.options_exit_monitor_interval_seconds

    import time as _time
    _now = _time.monotonic()
    last_options = _now
    last_regime  = _now
    last_greeks  = 0.0   # Greeks update on first tick is fine (lightweight)
    last_fills   = 0.0
    last_exit    = 0.0

    import time

    reconnect_interval_s = 60   # Check broker connection every 60s
    last_reconnect = 0.0

    while True:
        try:
            now = time.monotonic()

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

            # Every 30 min: unified options intelligence scan
            if now - last_options >= options_interval_s:
                await _run_options_scan()
                last_options = now

            # Exit monitor: enforce mode profit/DTE/stop rules on open positions
            if now - last_exit >= exit_interval_s:
                await _run_exit_monitor()
                last_exit = now

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


async def _run_options_scan() -> None:
    """
    Alpha Options unified scan — regime → strategy → AI → mode → execution.
    Delegates to options_engine (replaces legacy simplified Black-Scholes path).
    """
    try:
        from app.services.options_engine import options_engine
        actions = await options_engine.scan(_current_regime)
        if actions:
            logger.info("Options engine: %d action(s)", len(actions))
    except Exception as exc:
        logger.warning("Options scan failed: %s", exc)


async def _run_exit_monitor() -> None:
    """Evaluate open positions against trading-mode exit rules."""
    try:
        from app.services.position_exit_monitor import position_exit_monitor
        results = await position_exit_monitor.run()
        if results:
            logger.info("Exit monitor closed %d position(s)", len(results))
    except Exception as exc:
        logger.debug("Exit monitor: %s", exc)


async def _poll_fills() -> None:
    """
    Compare live broker positions against open DB trades.
    When a position disappears from IBKR (fully closed), fetch the actual
    fill price from IBKR execution history and record the real P&L.
    """
    try:
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

        # Load all open trades from DB
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Trade).where(Trade.status == "open")
            )
            open_trades = result.scalars().all()

        if not open_trades:
            return

        # Fetch recent IBKR executions once — keyed by symbol → avg fill price
        exit_prices: dict[str, float] = {}
        try:
            ib = getattr(broker, "ib", None)
            if ib is not None:
                import asyncio
                from ib_insync import ExecutionFilter
                fills = await asyncio.wait_for(
                    ib.reqExecutionsAsync(ExecutionFilter()),
                    timeout=5.0,
                )
                # Group fills by symbol, average the fill prices weighted by shares
                sym_total: dict[str, float] = {}
                sym_shares: dict[str, float] = {}
                for fill in fills:
                    sym = (fill.contract.symbol or "").upper()
                    shares = abs(fill.execution.shares or 0)
                    price  = fill.execution.price or 0
                    if sym and shares > 0:
                        sym_total[sym]  = sym_total.get(sym, 0) + price * shares
                        sym_shares[sym] = sym_shares.get(sym, 0) + shares
                for sym, total in sym_total.items():
                    exit_prices[sym] = round(total / sym_shares[sym], 4)
        except Exception as _exec_exc:
            logger.debug("Could not fetch IBKR executions: %s", _exec_exc)

        for trade in open_trades:
            underlying = (trade.underlying or "").upper()
            if not underlying or underlying in live_symbols:
                continue  # still open — skip

            # Get actual exit price from execution history, fall back to entry price
            exit_price = exit_prices.get(underlying)
            entry_price = float(trade.credit_received or trade.short_strike or 0)

            if exit_price is not None:
                cost_to_close = exit_price
                exit_reason   = "position_closed_at_broker"
            else:
                # No execution data — use entry price so P&L = 0 (neutral, not fake profit)
                cost_to_close = entry_price
                exit_reason   = "position_closed_at_broker_estimated"

            await trade_recorder.record_exit(
                trade_id=str(trade.id),
                cost_to_close=cost_to_close,
                exit_reason=exit_reason,
            )
            logger.info(
                "Auto-closed %s (%s) — exit_price=%.4f source=%s",
                trade.id, underlying, cost_to_close,
                "ibkr_execution" if exit_price is not None else "estimated",
            )

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
            if getattr(pos, "option_type", None):
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
            trades_today = int((await session.execute(
                select(func.count(Trade.id)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) == today)
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
