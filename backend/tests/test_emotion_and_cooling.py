"""
Batch 3 follow-ups — 3-C (EmotionGuard wiring) and 3-D (cooling-off enforcement).

3-C: EmotionGuard is now a process-global singleton shared by every
     UnifiedRiskEngine and by TradeRecorder.record_exit. Recording losses on it
     must make the engine the gate uses block subsequent orders.

3-D: A persisted cooling-off suspension (cooling_off_until) must block at the
     UnifiedRiskEngine the gate runs, for the full window — independent of
     whether the triggering loss metric has since cleared.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.guardrails import PortfolioState
from app.services.risk_manager import PortfolioRiskState
from app.services.unified_risk import (
    EmotionGuard, EmotionState, UnifiedRiskEngine, emotion_guard,
)


def _clean_pstate(cooling_off_until=None) -> PortfolioState:
    return PortfolioState(
        current_value=25_000.0, starting_capital=25_000.0,
        daily_pnl=0.0, weekly_pnl=0.0, monthly_pnl=0.0,
        consecutive_losses=0, trades_today=0,
        cooling_off_until=cooling_off_until,
    )


def _clean_prisk() -> PortfolioRiskState:
    return PortfolioRiskState(
        net_delta=0.0, net_vega=0.0, net_theta=0.0,
        open_position_count=0, portfolio_value=25_000.0,
        positions_by_underlying={}, positions_by_sector={},
    )


def _check(engine: UnifiedRiskEngine, pstate: PortfolioState):
    # instrument="option" skips the equity earnings gate; proposed_trade=None
    # skips the portfolio risk-manager leg — isolates guardrail + emotion checks.
    return engine.check(
        instrument_type="option", ticker="SPY",
        portfolio_state=pstate, portfolio_risk_state=_clean_prisk(),
        proposed_trade=None,
    )


@pytest.fixture(autouse=True)
def _reset_emotion():
    # The singleton persists across tests — reset before each.
    emotion_guard.state = EmotionState()
    yield
    emotion_guard.state = EmotionState()


# ── 3-C ──────────────────────────────────────────────────────────────────────
def test_emotion_guard_is_shared_singleton():
    # The gate's engine must consult the SAME guard that record_exit updates.
    assert UnifiedRiskEngine()._emotion is emotion_guard


def test_clean_state_allows():
    assert _check(UnifiedRiskEngine(), _clean_pstate()).allowed is True


def test_four_consecutive_losses_pauses_engine():
    engine = UnifiedRiskEngine()
    assert _check(engine, _clean_pstate()).allowed is True  # baseline

    # Simulate the close path recording 4 straight losses on the shared guard.
    for _ in range(EmotionGuard.CONSECUTIVE_LOSS_PAUSE):
        emotion_guard.record_trade(was_loss=True, position_size=500.0, baseline_size=500.0)

    decision = _check(engine, _clean_pstate())
    assert decision.allowed is False
    assert "emotion_guard" in decision.flags


def test_a_win_resets_consecutive_losses():
    for _ in range(3):
        emotion_guard.record_trade(was_loss=True, position_size=500.0, baseline_size=500.0)
    emotion_guard.record_trade(was_loss=False, position_size=500.0, baseline_size=500.0)
    assert emotion_guard.state.consecutive_losses == 0
    assert _check(UnifiedRiskEngine(), _clean_pstate()).allowed is True


# ── 3-D ──────────────────────────────────────────────────────────────────────
def test_future_cooling_off_blocks():
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    decision = _check(UnifiedRiskEngine(), _clean_pstate(cooling_off_until=future))
    assert decision.allowed is False
    assert "cooling_off_active" in decision.flags


def test_expired_cooling_off_allows():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    decision = _check(UnifiedRiskEngine(), _clean_pstate(cooling_off_until=past))
    assert decision.allowed is True
