"""
Tests for IV Surface and Regime Classifier.
Run with: pytest tests/test_new_modules.py -v
"""

from unittest.mock import AsyncMock, MagicMock
import pandas as pd
import numpy as np
import pytest

from app.services.iv_surface import IVSurfaceEngine, IVSurfaceSnapshot
from app.services.regime_classifier import RegimeClassifier, RegimeType


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_spy_returns(n: int = 60, trend: float = 0.0005) -> pd.Series:
    np.random.seed(42)
    returns = np.random.normal(trend, 0.01, n)
    return pd.Series(returns)


def make_fallback_surface(iv_rank: float = 45.0) -> IVSurfaceSnapshot:
    from datetime import datetime, timezone
    return IVSurfaceSnapshot(
        underlying="SPY",
        spot_price=455.0,
        fetched_at=datetime.now(timezone.utc),
        iv_rank=iv_rank,
        iv_percentile=iv_rank,
        atm_iv=0.18,
        realized_vol_20d=0.14,
        vrp=0.04,
        front_skew=None,
        back_skew=None,
        skew_trend=0.0,
        term_structure=None,
        data_quality="fallback",
        warnings=["test"],
    )


# ── IV Surface ────────────────────────────────────────────────────────────────

class TestIVSurfaceEngine:
    def test_load_iv_history_sets_history(self):
        broker = MagicMock()
        engine = IVSurfaceEngine(broker)
        iv_series = pd.Series(
            [0.18, 0.20, 0.22, 0.19, 0.25],
            index=pd.date_range("2024-01-01", periods=5),
        )
        engine.load_iv_history_from_df("SPY", iv_series)
        assert len(engine._iv_history["SPY"]) == 5

    def test_iv_rank_computed_from_history(self):
        broker = MagicMock()
        engine = IVSurfaceEngine(broker)
        ivs = list(range(10, 30))  # 10% to 29% IV
        iv_series = pd.Series(
            [v / 100 for v in ivs],
            index=pd.date_range("2024-01-01", periods=len(ivs)),
        )
        engine.load_iv_history_from_df("SPY", iv_series)
        rank = engine._compute_iv_rank(pd.Series([v / 100 for v in ivs]), 0.29)
        assert rank == pytest.approx(100.0, abs=1.0)

    def test_iv_rank_at_minimum(self):
        ivs = pd.Series([0.10, 0.15, 0.20, 0.25])
        rank = IVSurfaceEngine._compute_iv_rank(ivs, 0.10)
        assert rank == pytest.approx(0.0, abs=1.0)

    def test_iv_percentile_all_below(self):
        ivs = pd.Series([0.10, 0.12, 0.14, 0.16, 0.20])
        pct = IVSurfaceEngine._compute_iv_percentile(ivs, 0.20)
        assert pct == pytest.approx(80.0, abs=1.0)

    @pytest.mark.asyncio
    async def test_fallback_surface_always_valid(self):
        broker = MagicMock()
        broker.get_options_chain = AsyncMock(side_effect=Exception("no chain"))
        engine = IVSurfaceEngine(broker)
        surface = await engine.build_surface("SPY", 455.0, 0.14)
        assert surface.data_quality == "fallback"
        assert surface.iv_rank >= 0
        assert surface.iv_rank <= 100

    def test_fallback_surface_favorable_for_condor_when_high_iv(self):
        surface = make_fallback_surface(iv_rank=65.0)
        # High IV, no backwardation, no fear premium = favorable for condor
        assert surface.is_high_iv
        assert not surface.term_structure_in_backwardation
        assert not surface.fear_premium_elevated


# ── Regime Classifier ─────────────────────────────────────────────────────────

class TestRegimeClassifier:
    clf = RegimeClassifier()

    def test_crisis_on_high_vix(self):
        surface = make_fallback_surface(iv_rank=90.0)
        surface = IVSurfaceSnapshot(
            **{**surface.__dict__,
               "atm_iv": 0.50,  # VIX equivalent 50
               "iv_rank": 90.0}
        )
        returns = make_spy_returns()
        state = self.clf.classify(surface, rsi=35.0, adx=30.0, spy_returns=returns)
        assert state.regime == RegimeType.CRISIS
        assert not state.is_tradeable

    def test_normal_mean_revert_regime(self):
        surface = make_fallback_surface(iv_rank=45.0)
        # Low ADX (range-bound), moderate RSI, normal IV
        returns = make_spy_returns(trend=0.0001)  # Flat
        state = self.clf.classify(surface, rsi=50.0, adx=15.0, spy_returns=returns)
        assert state.regime == RegimeType.NORMAL_MEAN_REVERT
        assert state.iron_condor_allowed
        assert state.is_tradeable

    def test_high_vol_trending_regime(self):
        surface = make_fallback_surface(iv_rank=65.0)
        # High ADX (trending), elevated RSI
        returns = make_spy_returns(trend=0.003)  # Strong uptrend
        state = self.clf.classify(surface, rsi=68.0, adx=28.0, spy_returns=returns)
        assert state.regime == RegimeType.HIGH_VOL_TRENDING
        assert not state.iron_condor_allowed
        assert state.credit_spread_allowed

    def test_low_vol_trending_regime(self):
        surface = make_fallback_surface(iv_rank=18.0)
        returns = make_spy_returns(trend=0.002)
        state = self.clf.classify(surface, rsi=62.0, adx=25.0, spy_returns=returns)
        assert state.regime == RegimeType.LOW_VOL_TRENDING
        assert not state.credit_spread_allowed  # Low IV = no credit premium

    def test_crisis_disables_all_strategies(self):
        surface = make_fallback_surface(iv_rank=90.0)
        surface = IVSurfaceSnapshot(
            **{**surface.__dict__, "atm_iv": 0.45, "iv_rank": 88.0}
        )
        returns = make_spy_returns()
        state = self.clf.classify(surface, rsi=25.0, adx=40.0, spy_returns=returns)
        if state.regime == RegimeType.CRISIS:
            assert state.strategies_allowed == []
            assert state.size_multiplier == 0.0

    def test_confidence_between_0_and_1(self):
        surface = make_fallback_surface(iv_rank=45.0)
        returns = make_spy_returns()
        state = self.clf.classify(surface, rsi=50.0, adx=15.0, spy_returns=returns)
        assert 0.0 <= state.confidence <= 1.0

    def test_reasoning_populated(self):
        surface = make_fallback_surface(iv_rank=45.0)
        returns = make_spy_returns()
        state = self.clf.classify(surface, rsi=50.0, adx=15.0, spy_returns=returns)
        assert len(state.reasoning) > 0


# ── Strategy Optimizer ────────────────────────────────────────────────────────

# StrategyOptimizer tests moved to test_strategy_optimizer.py (real
# Backtester.run()-driven rewrite — see Track 2D).
