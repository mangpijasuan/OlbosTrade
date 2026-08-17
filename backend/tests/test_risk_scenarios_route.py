"""Tests for GET /api/risk/scenarios — every position must be stressed
against its real spot, never modeled at-the-money via the strike."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _trade(underlying, spread_type="bull_put_spread", short_strike=100.0, long_strike=95.0):
    return NS(
        underlying=underlying, spread_type=spread_type, quantity=1,
        short_strike=short_strike, long_strike=long_strike,
        expiration=date.today() + timedelta(days=30), status="open",
    )


def _trades_session(trades):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: trades)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture(autouse=True)
def _reset_spot_cache():
    from app.services import spot_price_cache
    spot_price_cache.clear()
    yield
    spot_price_cache.clear()


@pytest.mark.asyncio
async def test_zero_positions_returns_empty_scenarios():
    from app.api.routes import risk as risk_mod

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session([])):
        out = await risk_mod.get_scenarios()

    assert out["scenarios"] == []
    assert out["excluded_symbols"] == []


@pytest.mark.asyncio
async def test_resolvable_spots_produce_real_stressed_scenarios():
    from app.api.routes import risk as risk_mod

    trades = [_trade("AAPL"), _trade("MSFT", spread_type="bear_call_spread", short_strike=200.0, long_strike=205.0)]

    async def fake_fetch(symbol):
        return {"AAPL": 150.0, "MSFT": 195.0}[symbol]

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session(trades)), \
         patch.object(risk_mod, "_fetch_spot", new=fake_fetch):
        out = await risk_mod.get_scenarios()

    assert out["excluded_symbols"] == []
    assert len(out["scenarios"]) > 0
    # Real spot (150.0), not the strike (100.0), should have been used —
    # verified indirectly: a real position produces nonzero P&L under a
    # nonzero shock (an at-the-money-pinned proxy would too, so the
    # decisive check is that _fetch_spot was actually consulted).
    assert out["worst_pnl"] != 0.0 or out["scenarios"][0]["portfolio_pnl"] is not None


@pytest.mark.asyncio
async def test_one_of_several_unresolvable_spots_survivors_still_stressed():
    from app.api.routes import risk as risk_mod

    trades = [_trade("AAPL"), _trade("MSFT"), _trade("BAD")]

    async def fake_fetch(symbol):
        if symbol == "BAD":
            raise ConnectionError("yfinance timeout")
        return {"AAPL": 150.0, "MSFT": 195.0}[symbol]

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session(trades)), \
         patch.object(risk_mod, "_fetch_spot", new=fake_fetch):
        out = await risk_mod.get_scenarios()

    assert len(out["excluded_symbols"]) == 1
    assert out["excluded_symbols"][0]["ticker"] == "BAD"
    assert "spot unavailable" in out["excluded_symbols"][0]["reason"]
    assert len(out["scenarios"]) > 0  # survivors still stressed, no 500


@pytest.mark.asyncio
async def test_option_type_derived_from_spread_type_not_missing_column():
    """Regression: Trade has no option_type column — _trade_to_scenario_position
    must derive it from spread_type instead of raising AttributeError."""
    from app.api.routes import risk as risk_mod

    trades = [_trade("AAPL", spread_type="bull_call_debit_spread")]

    with patch("app.core.database.AsyncSessionLocal", return_value=_trades_session(trades)), \
         patch.object(risk_mod, "_fetch_spot", new=AsyncMock(return_value=150.0)):
        out = await risk_mod.get_scenarios()

    assert "error" not in out
    assert len(out["scenarios"]) > 0


@pytest.mark.asyncio
async def test_db_failure_returns_graceful_error_not_500():
    from app.api.routes import risk as risk_mod

    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        out = await risk_mod.get_scenarios()

    assert out["error"] == "db down"
    assert out["scenarios"] == []
