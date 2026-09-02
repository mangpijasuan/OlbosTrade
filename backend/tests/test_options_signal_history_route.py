"""Tests for GET /api/options/signals/history."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes import options as options_routes


def _row(**overrides) -> NS:
    base = dict(
        id="hist-1", ticker="SPY", strategy="bull_put_spread", action="SELL_SPREAD",
        confidence=0.82, pop=0.78, kelly_fraction=0.12, signal_score=0.65,
        quantity=2, iv_rank=45.0, regime="normal_mean_revert",
        option_type="put", short_strike=495.0, long_strike=490.0,
        expiration=date(2026, 9, 19), dte=34, net_credit=1.50, max_loss=3.50,
        breakeven=493.5, sigma=0.18, vix_used=16.5, credit_source="ibkr",
        evidence={"top_positive_factors": [], "top_negative_factors": []},
        intelligence={"pop": 0.78},
        generated_at=datetime(2026, 8, 16, 14, 30, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return NS(**base)


def _session(rows, total):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    rows_result = MagicMock()
    rows_result.scalars.return_value = MagicMock(all=lambda: rows)
    count_result = MagicMock()
    count_result.scalar_one.return_value = total
    session.execute = AsyncMock(side_effect=[rows_result, count_result])
    return session


@pytest.mark.asyncio
async def test_history_route_empty_store():
    with patch("app.core.database.AsyncSessionLocal", return_value=_session([], 0)):
        result = await options_routes.get_options_signal_history(limit=200, strategy=None, ticker=None)
    assert result == {"signals": [], "total": 0}


@pytest.mark.asyncio
async def test_history_route_returns_rows_with_nested_spread():
    row = _row()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session([row], 1)):
        result = await options_routes.get_options_signal_history(limit=200, strategy=None, ticker=None)

    assert result["total"] == 1
    sig = result["signals"][0]
    assert sig["ticker"] == "SPY"
    assert sig["strategy"] == "bull_put_spread"
    assert sig["spread"] == {
        "option_type": "put", "short_strike": 495.0, "long_strike": 490.0,
        "expiration": "2026-09-19", "dte": 34, "net_credit": 1.50,
        "max_loss": 3.50, "breakeven": 493.5,
    }
    assert sig["evidence"] == {"top_positive_factors": [], "top_negative_factors": []}


@pytest.mark.asyncio
async def test_history_route_nulls_pop_and_kelly_when_absent():
    row = _row(pop=None, kelly_fraction=None, intelligence=None)
    with patch("app.core.database.AsyncSessionLocal", return_value=_session([row], 1)):
        result = await options_routes.get_options_signal_history(limit=200, strategy=None, ticker=None)
    sig = result["signals"][0]
    assert sig["pop"] is None
    assert sig["kelly_fraction"] is None
    assert sig["intelligence"] is None


@pytest.mark.asyncio
async def test_history_route_total_reflects_filtered_count_not_page_length():
    """total must be a real filtered COUNT, not len(returned page) — a
    limit=1 request against 9 matching rows should still report total=9."""
    row = _row()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session([row], 9)):
        result = await options_routes.get_options_signal_history(limit=1, strategy=None, ticker=None)
    assert len(result["signals"]) == 1
    assert result["total"] == 9


@pytest.mark.asyncio
async def test_history_route_applies_strategy_and_ticker_filters():
    """Exercises the strategy/ticker filter branches (ticker uppercased to
    match the stored convention) — doesn't assert on the generated SQL
    itself, just that both filtered code paths run without error."""
    row = _row()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session([row], 1)):
        result = await options_routes.get_options_signal_history(
            limit=200, strategy="bull_put_spread", ticker="spy",
        )
    assert result["total"] == 1
