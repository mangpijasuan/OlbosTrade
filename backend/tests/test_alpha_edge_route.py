"""Tests for GET /api/alpha-edge/{ticker} and the I/O orchestrators in
app/services/alpha_edge_engine.py (pure scoring math is covered separately
in test_alpha_edge_engine.py)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _bars(n=250, start_price=100.0):
    base = datetime(2026, 1, 1)
    return [
        NS(timestamp=base + timedelta(days=i),
           open=start_price + i * 0.1, high=start_price + i * 0.1 + 1,
           low=start_price + i * 0.1 - 1, close=start_price + i * 0.1,
           volume=1_000_000)
        for i in range(n)
    ]


def _db_session(scalars_results: list):
    """Session whose successive .execute() calls return each item in
    scalars_results, in order, wrapped for .scalars().first()."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    results = []
    for row in scalars_results:
        r = MagicMock()
        r.scalars.return_value = MagicMock(first=lambda row=row: row)
        results.append(r)
    session.execute = AsyncMock(side_effect=results)
    return session


# ── compute_equity_alpha_edge ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_equity_no_position_no_anchor_returns_entry_only():
    from app.services import alpha_edge_engine as ae

    with patch("app.main._yf_bars", new=AsyncMock(return_value=_bars())), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([None])):
        result = await ae.compute_equity_alpha_edge("AAPL", broker=None)

    assert result.ticker == "AAPL"
    assert result.entry_score is not None
    assert result.hold_score is None and result.exit_score is None
    assert result.lifecycle_state == ae.NEW
    assert result.error is None


@pytest.mark.asyncio
async def test_equity_with_open_position_computes_hold_and_exit():
    from app.services import alpha_edge_engine as ae

    broker = MagicMock()
    broker.get_equity_positions = AsyncMock(return_value=[
        NS(symbol="AAPL", quantity=50, avg_cost=140.0),
    ])
    anchor = NS(status="pending", confidence=0.55,
                generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    with patch("app.main._yf_bars", new=AsyncMock(return_value=_bars())), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([anchor])):
        result = await ae.compute_equity_alpha_edge("AAPL", broker=broker)

    assert result.position["held"] is True
    assert result.hold_score is not None
    assert result.exit_score is not None
    assert result.exit_score == 100 - result.hold_score


@pytest.mark.asyncio
async def test_equity_broker_without_get_equity_positions_degrades_gracefully():
    """Alpaca-style broker with no get_equity_positions — must not crash,
    position must read as not-held rather than fabricating one."""
    from app.services import alpha_edge_engine as ae

    broker = MagicMock(spec=[])  # no get_equity_positions attribute at all

    with patch("app.main._yf_bars", new=AsyncMock(return_value=_bars())), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([None])):
        result = await ae.compute_equity_alpha_edge("AAPL", broker=broker)

    assert result.position == {"held": False}
    assert result.error is None


@pytest.mark.asyncio
async def test_equity_insufficient_bars_returns_honest_error():
    from app.services import alpha_edge_engine as ae

    with patch("app.main._yf_bars", new=AsyncMock(return_value=_bars(n=5))):
        result = await ae.compute_equity_alpha_edge("OBSCURE", broker=None)

    assert result.entry_score is None
    assert result.error is not None
    assert "insufficient" in result.error


@pytest.mark.asyncio
async def test_equity_broker_position_lookup_failure_does_not_block_scoring():
    from app.services import alpha_edge_engine as ae

    broker = MagicMock()
    broker.get_equity_positions = AsyncMock(side_effect=ConnectionError("broker down"))

    with patch("app.main._yf_bars", new=AsyncMock(return_value=_bars())), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([None])):
        result = await ae.compute_equity_alpha_edge("AAPL", broker=broker)

    assert result.error is None
    assert result.entry_score is not None
    assert result.position == {"held": False}


# ── compute_options_alpha_edge ───────────────────────────────────────────────

def _trade(**overrides):
    base = dict(
        underlying="SPY", status="open", quantity=2,
        short_strike=450.0, long_strike=445.0, credit_received=1.5,
        mae_pnl=-175.0, signal_score=0.65, entry_date=date(2026, 1, 1),
    )
    base.update(overrides)
    return NS(**base)


def _history(**overrides):
    base = dict(
        ticker="SPY", signal_score=0.7, net_credit=1.5, max_loss=3.5,
        generated_at=datetime.now(timezone.utc),
        evidence={"top_positive_factors": [{"feature": "iv_rank", "impact": 0.4}],
                  "top_negative_factors": []},
    )
    base.update(overrides)
    return NS(**base)


def _options_db_session(trade, history):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    trade_result = MagicMock()
    trade_result.scalars.return_value = MagicMock(first=lambda: trade)
    hist_result = MagicMock()
    hist_result.scalars.return_value = MagicMock(first=lambda: history)
    session.execute = AsyncMock(side_effect=[trade_result, hist_result])
    return session


@pytest.mark.asyncio
async def test_options_no_position_no_history_returns_new():
    from app.services import alpha_edge_engine as ae

    with patch("app.core.database.AsyncSessionLocal", return_value=_options_db_session(None, None)):
        result = await ae.compute_options_alpha_edge("XYZ")

    assert result.lifecycle_state == ae.NEW
    assert result.position == {"held": False}
    assert result.entry_score is None


@pytest.mark.asyncio
async def test_options_open_position_computes_exit_from_live_mae():
    from app.services import alpha_edge_engine as ae

    trade = _trade()
    with patch("app.core.database.AsyncSessionLocal", return_value=_options_db_session(trade, None)):
        result = await ae.compute_options_alpha_edge("SPY")

    # max_loss = (450-445)*100 - 1.5*100 = 350; mae -175 -> 50
    assert result.exit_score == 50
    assert result.hold_score == 50
    assert result.lifecycle_state == ae.CONFIRMED
    assert result.score_trend.direction == "not_tracked"


@pytest.mark.asyncio
async def test_options_closed_trade_is_expired():
    from app.services import alpha_edge_engine as ae

    trade = _trade(status="closed", mae_pnl=-300.0)
    with patch("app.core.database.AsyncSessionLocal", return_value=_options_db_session(trade, None)):
        result = await ae.compute_options_alpha_edge("SPY")

    assert result.lifecycle_state == ae.EXPIRED


@pytest.mark.asyncio
async def test_options_no_open_trade_uses_recent_history_for_entry_score():
    from app.services import alpha_edge_engine as ae

    history = _history()
    with patch("app.core.database.AsyncSessionLocal", return_value=_options_db_session(None, history)):
        result = await ae.compute_options_alpha_edge("SPY")

    assert result.entry_score is not None
    assert result.supporting_evidence == [{"feature": "iv_rank", "impact": 0.4}]


@pytest.mark.asyncio
async def test_options_stale_history_does_not_produce_entry_score():
    """A signal from 30 days ago must not silently masquerade as a fresh
    entry read — recency window enforced (5 trading days)."""
    from app.services import alpha_edge_engine as ae

    history = _history(generated_at=datetime.now(timezone.utc) - timedelta(days=30))
    with patch("app.core.database.AsyncSessionLocal", return_value=_options_db_session(None, history)):
        result = await ae.compute_options_alpha_edge("SPY")

    assert result.entry_score is None


@pytest.mark.asyncio
async def test_options_db_failure_returns_honest_error_not_500():
    from app.services import alpha_edge_engine as ae

    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        result = await ae.compute_options_alpha_edge("SPY")

    assert result.error is not None
    assert result.entry_score is None and result.hold_score is None


# ── route-level (serialization + dispatch) ───────────────────────────────────

@pytest.mark.asyncio
async def test_route_dispatches_to_options_engine_and_serializes():
    from app.api.routes import alpha_edge as route

    with patch("app.services.alpha_edge_engine.compute_options_alpha_edge",
               new=AsyncMock(return_value=_fake_alpha_edge_result())):
        out = await route.get_alpha_edge("SPY", asset_type="options")

    assert out["ticker"] == "SPY"
    assert out["asset_type"] == "options"
    assert isinstance(out["score_trend"], dict)


def _fake_alpha_edge_result():
    from app.services.alpha_edge_engine import AlphaEdgeResult, ScoreTrend
    return AlphaEdgeResult(
        ticker="SPY", asset_type="options",
        entry_score=60, hold_score=None, exit_score=None,
        exit_score_basis="live_mae_vs_max_loss", risk_score=30,
        lifecycle_state="new", score_trend=ScoreTrend("not_tracked", None, "n/a"),
        current_action=None, current_confidence=None,
        position={"held": False},
    )
