"""Tests for GET /api/options/signals store + list handler (no full app boot)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.api.routes import options as options_routes


@pytest.fixture(autouse=True)
def _clear_store():
    options_routes._recent_options_signals.clear()
    yield
    options_routes._recent_options_signals.clear()


@pytest.mark.asyncio
async def test_list_options_signals_empty():
    body = await options_routes.list_options_signals()
    assert body["signals"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_default_limit_covers_a_full_watchlist_cycle():
    """The default was 50 — a single scan cycle across the equity
    watchlist (102 tickers as of the Nasdaq-100 switch) can produce one
    entry per ticker, so 50 silently truncated a full cycle to half of
    it. Must stay comfortably above the current watchlist size."""
    import inspect
    default = inspect.signature(options_routes.list_options_signals).parameters["limit"].default
    assert default >= 102


@pytest.mark.asyncio
async def test_list_options_signals_returns_stored():
    options_routes._recent_options_signals.append({
        "id": "opt-1",
        "ticker": "SPY",
        "asset_type": "options",
        "source": "Options Signal Scanner",
        "action": "SELL_SPREAD",
        "confidence": 0.72,
        "strategy": "bull_put_spread",
        "spread": {
            "option_type": "put",
            "short_strike": 500,
            "long_strike": 495,
            "dte": 32,
            "net_credit": 0.85,
            "max_loss": 415.0,
            "breakeven": 499.15,
        },
    })
    body = await options_routes.list_options_signals(limit=10)
    assert body["total"] == 1
    assert body["signals"][0]["ticker"] == "SPY"
    assert body["signals"][0]["source"] == "Options Signal Scanner"
    assert body["signals"][0]["action"] == "SELL_SPREAD"


@pytest.mark.asyncio
async def test_trigger_scan_never_executes():
    """
    The on-demand "show me current signals" preview must never itself submit
    an order -- it has to call the shared scanner with execute=False, not
    the default execute=True the scheduled background scanner uses. A UI
    action that looks like a passive refresh must never depend on hidden
    execution-mode state to decide whether it places a real trade.

    Also covers the full equity watchlist now, not just SPY/QQQ, since the
    background scanner was widened to scan every watchlist symbol.
    """
    from app.core.config import settings

    watchlist = settings.get_equity_watchlist()

    with patch("app.main._run_options_scan", new=AsyncMock()) as mock_scan:
        await options_routes.trigger_options_signal_scan()

    assert mock_scan.await_count == len(watchlist)
    for call in mock_scan.await_args_list:
        args, kwargs = call.args, call.kwargs
        symbol = args[0] if args else kwargs.get("symbol")
        assert symbol in watchlist
        assert kwargs.get("execute") is False, (
            "preview scan must pass execute=False so it can never dispatch to "
            "handle_signal()/order submission"
        )


@pytest.mark.asyncio
async def test_trigger_scan_survives_one_symbol_failing():
    from app.core.config import settings

    watchlist = settings.get_equity_watchlist()

    async def _side_effect(symbol, execute=True):
        if symbol == watchlist[0]:
            raise RuntimeError("yfinance down")

    with patch("app.main._run_options_scan", new=AsyncMock(side_effect=_side_effect)) as mock_scan:
        result = await options_routes.trigger_options_signal_scan()

    assert mock_scan.await_count == len(watchlist)
    assert "signals" in result and "total" in result
