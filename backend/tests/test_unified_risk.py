"""Tests for the Unified Risk Engine + EmotionGuard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.unified_risk import EmotionGuard, UnifiedRiskEngine, RiskDecision
from app.services.guardrails import PortfolioState
from app.services.risk_manager import PortfolioRiskState, ProposedTrade


# ── EmotionGuard logic ───────────────────────────────────────────────────────
def test_consecutive_losses_increment_and_reset():
    g = EmotionGuard()
    g.record_trade(was_loss=True, position_size=500, baseline_size=500)
    g.record_trade(was_loss=True, position_size=500, baseline_size=500)
    assert g.state.consecutive_losses == 2
    g.record_trade(was_loss=False, position_size=500, baseline_size=500)
    assert g.state.consecutive_losses == 0


def test_pause_after_four_losses():
    g = EmotionGuard()
    for _ in range(4):
        g.record_trade(was_loss=True, position_size=500, baseline_size=500)
    assert g.state.paused_until is not None
    allowed, reason = g.check()
    assert allowed is False and "pause active" in reason


def test_size_drift_tracked():
    g = EmotionGuard()
    g.record_trade(was_loss=False, position_size=750, baseline_size=500)
    assert abs(g.state.position_size_drift - 0.5) < 1e-9


def test_check_auto_resumes_after_pause_expires():
    g = EmotionGuard()
    g.state.paused_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    g.state.consecutive_losses = 5
    allowed, reason = g.check()
    assert allowed is True and reason is None
    assert g.state.paused_until is None and g.state.consecutive_losses == 0


def test_check_allows_when_no_pause():
    assert EmotionGuard().check() == (True, None)


# ── EmotionGuard DB rehydrate / persist ──────────────────────────────────────
def _sessionlocal(row=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    res = MagicMock()
    res.scalar_one_or_none = lambda: row
    session.execute = AsyncMock(return_value=res)
    session.commit = AsyncMock()
    return MagicMock(return_value=session), session


@pytest.mark.asyncio
async def test_rehydrate_from_db():
    paused = datetime.now(timezone.utc) + timedelta(hours=3)
    snap = MagicMock(consecutive_losses=3, cooling_off_until=paused)
    local, _ = _sessionlocal(row=snap)
    g = EmotionGuard()
    with patch("app.core.database.AsyncSessionLocal", local):
        await g.rehydrate_from_db()
    assert g.state.consecutive_losses == 3 and g.state.paused_until == paused


@pytest.mark.asyncio
async def test_rehydrate_handles_no_row():
    local, _ = _sessionlocal(row=None)
    g = EmotionGuard()
    with patch("app.core.database.AsyncSessionLocal", local):
        await g.rehydrate_from_db()
    assert g.state.consecutive_losses == 0


@pytest.mark.asyncio
async def test_persist_to_db_writes_and_commits():
    row = MagicMock()
    local, session = _sessionlocal(row=row)
    g = EmotionGuard()
    g.state.consecutive_losses = 2
    with patch("app.core.database.AsyncSessionLocal", local):
        await g._persist_to_db()
    assert row.consecutive_losses == 2
    session.commit.assert_awaited()


# ── UnifiedRiskEngine orchestration ──────────────────────────────────────────
def _pstate():
    return PortfolioState(current_value=100000, starting_capital=100000,
                          daily_pnl=Decimal("0"), weekly_pnl=Decimal("0"),
                          monthly_pnl=Decimal("0"), consecutive_losses=0, trades_today=0)


def _prisk():
    return PortfolioRiskState(net_delta=0, net_vega=0, net_theta=0, open_position_count=0,
                              portfolio_value=100000, positions_by_underlying={}, positions_by_sector={})


def test_engine_blocks_on_guardrail():
    eng = UnifiedRiskEngine()
    eng._guardrail = MagicMock()
    eng._guardrail.check_all.return_value = MagicMock(trading_allowed=False, reason="daily loss", flags=["daily"])
    d = eng.check("option", "SPY", _pstate(), _prisk())
    assert not d.allowed and "guardrail_block" in d.flags


def test_engine_blocks_on_emotion():
    eng = UnifiedRiskEngine()
    eng._guardrail = MagicMock()
    eng._guardrail.check_all.return_value = MagicMock(trading_allowed=True, reason=None, flags=[])
    eng._emotion.state.paused_until = datetime.now(timezone.utc) + timedelta(hours=2)
    d = eng.check("option", "SPY", _pstate(), _prisk())
    assert not d.allowed and "emotion_guard" in d.flags


def test_engine_blocks_on_earnings():
    eng = UnifiedRiskEngine()
    eng._guardrail = MagicMock()
    eng._guardrail.check_all.return_value = MagicMock(trading_allowed=True, reason=None, flags=[])
    with patch("app.services.equity_signal_engine.earnings_gate", return_value=True):
        d = eng.check("equity", "AAPL", _pstate(), _prisk())
    assert not d.allowed and "earnings_gate" in d.flags


def test_engine_blocks_on_risk_manager():
    eng = UnifiedRiskEngine()
    eng._guardrail = MagicMock()
    eng._guardrail.check_all.return_value = MagicMock(trading_allowed=True, reason=None, flags=[])
    eng._risk_mgr = MagicMock()
    eng._risk_mgr.approve_trade.return_value = MagicMock(approved=False, reason="delta", flags=["delta_limit"])
    trade = ProposedTrade(strategy="bps", underlying="SPY", sector="Index",
                          delta=0.4, vega=0.0, max_loss_dollars=500)
    d = eng.check("option", "SPY", _pstate(), _prisk(), proposed_trade=trade)
    assert not d.allowed and "risk_manager_block" in d.flags


def test_engine_allows_clean_trade():
    eng = UnifiedRiskEngine()
    eng._guardrail = MagicMock()
    eng._guardrail.check_all.return_value = MagicMock(trading_allowed=True, reason=None, flags=[])
    d = eng.check("option", "SPY", _pstate(), _prisk(), check_earnings=False)
    assert d.allowed and isinstance(d, RiskDecision)


@pytest.mark.asyncio
async def test_record_trade_result_persists():
    eng = UnifiedRiskEngine()
    eng._emotion._persist_to_db = AsyncMock()
    await eng.record_trade_result(was_loss=True, position_size=500)
    assert eng.emotion_state.consecutive_losses == 1
    eng._emotion._persist_to_db.assert_awaited()


# ── remaining branches ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rehydrate_and_persist_swallow_db_errors():
    g = EmotionGuard()
    boom = MagicMock(side_effect=Exception("db down"))
    with patch("app.core.database.AsyncSessionLocal", boom):
        await g.rehydrate_from_db()      # must not raise
        await g._persist_to_db()         # must not raise


def test_record_trade_stale_last_trade_resets_count():
    g = EmotionGuard()
    g.state.last_trade_at = datetime.now(timezone.utc) - timedelta(hours=2)
    g.record_trade(was_loss=False, position_size=500, baseline_size=500)
    assert g.state.recent_trade_count_1h == 1


def test_record_trade_zero_baseline_no_drift():
    g = EmotionGuard()
    g.record_trade(was_loss=False, position_size=900, baseline_size=0)
    assert g.state.position_size_drift == 0.0


def test_engine_earnings_pass_then_allowed():
    eng = UnifiedRiskEngine()
    eng._guardrail = MagicMock()
    eng._guardrail.check_all.return_value = MagicMock(trading_allowed=True, reason=None, flags=[])
    with patch("app.services.equity_signal_engine.earnings_gate", return_value=False):
        d = eng.check("equity", "AAPL", _pstate(), _prisk())
    assert d.allowed


def test_engine_risk_manager_approved_extends_flags():
    eng = UnifiedRiskEngine()
    eng._guardrail = MagicMock()
    eng._guardrail.check_all.return_value = MagicMock(trading_allowed=True, reason=None, flags=[])
    eng._risk_mgr = MagicMock()
    eng._risk_mgr.approve_trade.return_value = MagicMock(approved=True, reason=None, flags=["sector_concentration_warning"])
    trade = ProposedTrade(strategy="bps", underlying="SPY", sector="Index",
                          delta=0.01, vega=0.0, max_loss_dollars=500)
    d = eng.check("option", "SPY", _pstate(), _prisk(), proposed_trade=trade, check_earnings=False)
    assert d.allowed and "sector_concentration_warning" in d.flags

