"""Tests for TradeRecorder — fill recording, exit P&L, unknown-close."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.trade_recorder import TradeRecorder


def _session(trade=None):
    """AsyncSessionLocal mock supporting `async with`, .begin(), execute, get."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    begin = AsyncMock()
    begin.__aenter__ = AsyncMock(return_value=session)
    begin.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin)
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: trade))
    session.get = AsyncMock(return_value=trade)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


class _Trade:
    """Capture object standing in for a Trade row."""
    def __init__(self, **kw):
        self.cost_to_close = self.pnl = self.pnl_pct = None
        self.status = self.exit_date = self.exit_reason = None
        for k, v in kw.items():
            setattr(self, k, v)


# ── record_fill ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_record_fill_success_returns_trade_id():
    session = _session(trade=None)   # no existing dispatch_id
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        tid = await rec.record_fill(
            strategy="bull_put_spread", underlying="SPY", option_type="put",
            short_strike=450, long_strike=445, expiration=date(2025, 6, 20),
            entry_credit=1.50, quantity=1, signal_score=0.8, iv_rank=40,
            regime="neutral", trading_mode="balanced", dispatch_id="D-1",
        )
    assert tid and len(tid) == 36          # uuid string
    assert session.add.call_count == 2     # Trade + JournalEntry


@pytest.mark.asyncio
async def test_record_fill_db_failure_returns_none():
    session = _session(trade=None)
    session.execute = AsyncMock(side_effect=Exception("db down"))
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        tid = await rec.record_fill(
            strategy="equity", underlying="AAPL", option_type="equity_long",
            short_strike=0, long_strike=0, expiration=date(2025, 1, 1),
            entry_credit=150, quantity=10, signal_score=0.7, iv_rank=0,
            regime="x", trading_mode="balanced", dispatch_id="D-2",
        )
    assert tid is None


# ── record_exit ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_record_exit_equity_long():
    t = _Trade(credit_received=Decimal("100"), quantity=1,
               spread_type="equity_long", strategy="equity")
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(trade=t)):
        ok = await rec.record_exit(trade_id=str(uuid.uuid4()), cost_to_close=110.0,
                                   exit_reason="target")
    assert ok and float(t.pnl) == 10.0 and t.status == "closed"   # (110-100)*1


@pytest.mark.asyncio
async def test_record_exit_equity_short():
    t = _Trade(credit_received=Decimal("100"), quantity=1,
               spread_type="equity_short", strategy="equity")
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(trade=t)):
        await rec.record_exit(trade_id=str(uuid.uuid4()), cost_to_close=90.0, exit_reason="cover")
    assert float(t.pnl) == 10.0          # short: entry - exit = 100 - 90


@pytest.mark.asyncio
async def test_record_exit_options_multiplier_100():
    t = _Trade(credit_received=Decimal("1.50"), quantity=2, spread_type="put", strategy="bull_put_spread")
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(trade=t)):
        await rec.record_exit(trade_id=str(uuid.uuid4()), cost_to_close=0.50, exit_reason="profit")
    assert float(t.pnl) == 200.0         # (1.5-0.5)*2*100


@pytest.mark.asyncio
async def test_record_exit_trade_not_found():
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(trade=None)):
        ok = await rec.record_exit(trade_id=str(uuid.uuid4()), cost_to_close=1.0, exit_reason="x")
    assert ok is False


@pytest.mark.asyncio
async def test_record_exit_handles_exception():
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("boom")):
        ok = await rec.record_exit(trade_id=str(uuid.uuid4()), cost_to_close=1.0, exit_reason="x")
    assert ok is False


# ── record_close_unknown ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_record_close_unknown_sets_null_pnl():
    t = _Trade(status="open")
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(trade=t)):
        ok = await rec.record_close_unknown(trade_id=str(uuid.uuid4()),
                                            exit_reason="closed_price_unavailable")
    assert ok and t.status == "closed" and t.pnl is None


@pytest.mark.asyncio
async def test_record_close_unknown_not_found():
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(trade=None)):
        ok = await rec.record_close_unknown(trade_id=str(uuid.uuid4()), exit_reason="x")
    assert ok is False


@pytest.mark.asyncio
async def test_record_close_unknown_handles_exception():
    rec = TradeRecorder()
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("boom")):
        ok = await rec.record_close_unknown(trade_id=str(uuid.uuid4()), exit_reason="x")
    assert ok is False
