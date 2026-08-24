"""
Tests for rotation_correlation_cache.refresh() — the periodic job that
populates the cache position_rotation.py's tiebreaker reads. Mirrors
test_portfolio_correlation_route.py's exact mocking pattern (same
AsyncSessionLocal/_yf_bars/get_account_value patches) since refresh()
reuses that route's fetch/compute pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import rotation_correlation_cache as cache

BASE = datetime(2026, 1, 1)


def _trade(underlying, risk_dollars=1000.0, spread_type="equity_long"):
    return NS(underlying=underlying, quantity=1, spread_type=spread_type,
              strategy="equity", credit_received=risk_dollars,
              short_strike=0, long_strike=0)


def _bars(n, start_price=100.0, step=1.0, start=BASE):
    return [NS(timestamp=start + timedelta(days=i), close=start_price + step * i) for i in range(n)]


def _trades_session(trades):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: trades)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture(autouse=True)
def _reset_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.asyncio
async def test_fewer_than_two_open_equity_tickers_leaves_cache_untouched():
    cache._store(flagged_clusters=[{"tickers": ["ZZZZ"], "avg_correlation": 1.0}],
                 covered_tickers={"ZZZZ"})

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session([_trade("AAPL")])), \
         patch("app.services.account_state.get_account_value", new=AsyncMock(return_value=100_000.0)), \
         patch("app.main._yf_bars", new=AsyncMock()) as mock_bars:
        await cache.refresh()

    mock_bars.assert_not_called()
    assert cache.in_flagged_cluster("ZZZZ") is True  # untouched, not cleared


@pytest.mark.asyncio
async def test_db_failure_leaves_cache_untouched():
    cache._store(flagged_clusters=[{"tickers": ["ZZZZ"], "avg_correlation": 1.0}],
                 covered_tickers={"ZZZZ"})

    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        await cache.refresh()

    assert cache.in_flagged_cluster("ZZZZ") is True


@pytest.mark.asyncio
async def test_fetch_failure_for_all_tickers_leaves_cache_untouched():
    cache._store(flagged_clusters=[{"tickers": ["ZZZZ"], "avg_correlation": 1.0}],
                 covered_tickers={"ZZZZ"})
    trades = [_trade("AAPL"), _trade("MSFT")]

    async def fake_bars(ticker, limit=60):
        raise RuntimeError("yfinance timeout")

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session(trades)), \
         patch("app.services.account_state.get_account_value", new=AsyncMock(return_value=100_000.0)), \
         patch("app.main._yf_bars", new=AsyncMock(side_effect=fake_bars)):
        await cache.refresh()

    assert cache.in_flagged_cluster("ZZZZ") is True


@pytest.mark.asyncio
async def test_successful_refresh_populates_flagged_clusters_only():
    trades = [
        _trade("AAPL", risk_dollars=8000.0),
        _trade("MSFT", risk_dollars=8000.0),
        _trade("TSLA", risk_dollars=10.0),   # tiny position, won't breach the cap
    ]

    async def fake_bars(ticker, limit=60):
        if ticker in ("AAPL", "MSFT"):
            # Perfectly correlated, lockstep movement.
            return _bars(40, start_price=100.0 if ticker == "AAPL" else 300.0,
                         step=1.0 if ticker == "AAPL" else 2.0)
        # TSLA moves independently (uncorrelated-ish random walk via alternating steps).
        return _bars(40, start_price=50.0, step=-1.0)

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session(trades)), \
         patch("app.services.account_state.get_account_value", new=AsyncMock(return_value=20_000.0)), \
         patch("app.main._yf_bars", new=AsyncMock(side_effect=fake_bars)):
        await cache.refresh()

    assert cache.in_flagged_cluster("AAPL") is True
    assert cache.in_flagged_cluster("MSFT") is True
    assert cache.in_flagged_cluster("TSLA") is False   # covered, not flagged
    assert cache.in_flagged_cluster("NEVER_SEEN") is None


@pytest.mark.asyncio
async def test_refresh_only_considers_equity_spread_types():
    trades = [
        _trade("AAPL", risk_dollars=8000.0, spread_type="equity_long"),
        _trade("MSFT", risk_dollars=8000.0, spread_type="equity_long"),
        _trade("SPY", risk_dollars=8000.0, spread_type="bull_put_spread"),
    ]

    async def fake_bars(ticker, limit=60):
        return _bars(40, start_price=100.0 if ticker == "AAPL" else 300.0,
                     step=1.0 if ticker == "AAPL" else 2.0)

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session(trades)), \
         patch("app.services.account_state.get_account_value", new=AsyncMock(return_value=20_000.0)), \
         patch("app.main._yf_bars", new=AsyncMock(side_effect=fake_bars)) as mock_bars:
        await cache.refresh()

    called_tickers = {c.args[0] for c in mock_bars.call_args_list}
    assert "SPY" not in called_tickers
    assert cache.in_flagged_cluster("SPY") is None
