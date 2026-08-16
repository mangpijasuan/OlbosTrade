"""Tests for options_signal_history — persistence of qualifying options spread signals."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.options_signal_history import record_options_signal


def _signal(**overrides) -> dict:
    base = {
        "id": "sig-1", "ticker": "SPY", "strategy": "bull_put_spread",
        "action": "SELL_SPREAD", "confidence": 0.82, "pop": 0.78,
        "kelly_fraction": 0.12, "signal_score": 0.65, "quantity": 2,
        "iv_rank": 45.0, "regime": "normal_mean_revert",
        "generated_at": "2026-08-16T14:30:00+00:00",
        "evidence": {"top_positive_factors": [], "top_negative_factors": []},
        "intelligence": {"pop": 0.78, "delta_short": -0.2},
        "spread": {
            "option_type": "put", "short_strike": 495.0, "long_strike": 490.0,
            "expiration": "2026-09-19", "dte": 34, "net_credit": 1.50,
            "max_loss": 3.50, "breakeven": 493.5,
        },
        "sigma": 0.18, "vix_used": 16.5, "credit_source": "ibkr",
    }
    base.update(overrides)
    return base


def _session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    begin = AsyncMock()
    begin.__aenter__ = AsyncMock(return_value=session)
    begin.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin)
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_record_options_signal_noop_for_hold():
    result = await record_options_signal({"action": "HOLD", "ticker": "SPY"})
    assert result is None


@pytest.mark.asyncio
async def test_record_options_signal_noop_without_spread():
    result = await record_options_signal({"action": "SELL_SPREAD", "ticker": "SPY", "spread": {}})
    assert result is None


@pytest.mark.asyncio
async def test_record_options_signal_inserts_row():
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        result = await record_options_signal(_signal())

    assert result is not None
    assert session.add.call_count == 1
    inserted = session.add.call_args.args[0]
    assert inserted.ticker == "SPY"
    assert inserted.strategy == "bull_put_spread"
    assert inserted.action == "SELL_SPREAD"
    assert float(inserted.pop) == 0.78
    assert float(inserted.kelly_fraction) == 0.12
    assert inserted.option_type == "put"
    assert float(inserted.short_strike) == 495.0
    assert float(inserted.long_strike) == 490.0
    assert inserted.dte == 34
    assert float(inserted.net_credit) == 1.50
    assert inserted.evidence == {"top_positive_factors": [], "top_negative_factors": []}
    assert inserted.intelligence == {"pop": 0.78, "delta_short": -0.2}


@pytest.mark.asyncio
async def test_record_options_signal_debit_spread_nulls_pop_and_kelly():
    """Matches app.main's own comment: analyze_spread() is skipped for debit
    spreads, so pop/kelly_fraction/intelligence are genuinely None there —
    the row must carry that absence honestly, not a fabricated 0."""
    session = _session()
    signal = _signal(action="BUY_SPREAD", pop=None, kelly_fraction=None, intelligence=None)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        result = await record_options_signal(signal)

    assert result is not None
    inserted = session.add.call_args.args[0]
    assert inserted.action == "BUY_SPREAD"
    assert inserted.pop is None
    assert inserted.kelly_fraction is None
    assert inserted.intelligence is None


@pytest.mark.asyncio
async def test_record_options_signal_returns_none_on_db_failure():
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        result = await record_options_signal(_signal())
    assert result is None
