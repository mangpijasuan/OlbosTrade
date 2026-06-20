"""Tests for Alpha Options unified pipeline helpers."""

from datetime import date, timedelta

import pytest

from app.services.strategy_engine import BullPutSpread, _mode_exit_params
from app.services.trading_mode import (
    TradingModeType,
    is_strategy_allowed_by_mode,
    select_expiry_within_bounds,
    trading_mode_manager,
)


class TestTradingModeHelpers:
    def setup_method(self):
        trading_mode_manager.set_mode(TradingModeType.BALANCED)

    def test_select_expiry_within_balanced_bounds(self):
        expiry, dte = select_expiry_within_bounds(22, 15, 30)
        assert expiry is not None
        assert 15 <= dte <= 30

    def test_scalper_allows_zero_dte(self):
        trading_mode_manager.set_mode(TradingModeType.SCALPER)
        expiry, dte = select_expiry_within_bounds(1, 0, 3, prefer_friday=False)
        assert expiry is not None
        assert 0 <= dte <= 3

    def test_scalper_blocks_iron_condor(self):
        trading_mode_manager.set_mode(TradingModeType.SCALPER)
        assert is_strategy_allowed_by_mode("bull_put_spread") is True
        assert is_strategy_allowed_by_mode("iron_condor") is False

    def test_conservative_blocks_debit_spread(self):
        trading_mode_manager.set_mode(TradingModeType.CONSERVATIVE)
        assert is_strategy_allowed_by_mode("bull_put_spread") is True
        assert is_strategy_allowed_by_mode("bull_call_debit_spread") is False


class TestModeAwareExit:
    def setup_method(self):
        trading_mode_manager.set_mode(TradingModeType.AGGRESSIVE)

    def test_exit_uses_mode_dte_and_profit(self):
        profit_target, dte_exit, stop_mult = _mode_exit_params()
        assert profit_target == 0.35
        assert dte_exit == 2
        assert stop_mult == 1.5

        strategy = BullPutSpread()
        decision = strategy.check_exit(
            entry_credit=100.0,
            current_value=60.0,  # 40% profit
            dte_remaining=5,
            short_strike_breached=False,
        )
        assert decision.should_exit is True
        assert "35%" in (decision.reason or "")

    def test_exit_triggers_at_mode_dte_stop(self):
        trading_mode_manager.set_mode(TradingModeType.BALANCED)
        strategy = BullPutSpread()
        decision = strategy.check_exit(
            entry_credit=100.0,
            current_value=90.0,
            dte_remaining=10,
            short_strike_breached=False,
        )
        assert decision.should_exit is True
        assert "10 DTE" in (decision.reason or "")


class TestSignalScorerDte:
    def test_mode_relative_dte_score_peak_at_target(self):
        from app.services.signal_scorer import SignalScorer

        trading_mode_manager.set_mode(TradingModeType.SCALPER)
        scorer = SignalScorer()
        peak = scorer._mode_relative_dte_score(1.0)
        edge = scorer._mode_relative_dte_score(3.0)
        out_of_bounds = scorer._mode_relative_dte_score(10.0)
        assert peak > edge
        assert out_of_bounds == 0.2
