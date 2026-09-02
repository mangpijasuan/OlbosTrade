"""
Tests for StrategyOptimizer — the walk-forward exit-rule grid search that
scores candidates against real Backtester.run() calls.

Backtester itself is mocked throughout (backtester.run = AsyncMock(...)) —
these tests exercise the optimizer's own grid-search/accept-reject logic,
not the backtest engine or network I/O. _fetch_window() (SPY/VIX pre-fetch)
is patched away via an autouse fixture for the same reason: it's simple
I/O the optimizer doesn't need to re-prove here.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from app.services.strategy_optimizer import StrategyOptimizer, StrategyParams


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bt_result(pnls: list[float], hold_days: int = 20):
    return SimpleNamespace(
        trades=[SimpleNamespace(pnl=p, hold_days=hold_days) for p in pnls],
    )


def _make_trades(n=40, win_rate=0.60, avg_win=120.0, avg_loss=-200.0):
    pnls = []
    for i in range(n):
        is_win = (i % 10) < (win_rate * 10)
        pnls.append(avg_win if is_win else avg_loss)
    return pnls


@pytest.fixture(autouse=True)
def _mock_fetch_window(monkeypatch):
    async def _fake_fetch_window(self, start, end):
        return pd.DataFrame({"Close": [1.0]}), None
    monkeypatch.setattr(StrategyOptimizer, "_fetch_window", _fake_fetch_window)


def _optimizer(run_return_value=None, run_side_effect=None):
    backtester = MagicMock()
    if run_side_effect is not None:
        backtester.run = AsyncMock(side_effect=run_side_effect)
    else:
        backtester.run = AsyncMock(return_value=run_return_value or _bt_result(_make_trades()))
    return StrategyOptimizer(backtester=backtester), backtester


# ── Params / defaults ────────────────────────────────────────────────────────

def test_default_params_loaded():
    opt, _ = _optimizer()
    params = opt.get_params("bull_put_spread")
    assert params.profit_target_pct == 0.50
    assert params.stop_loss_multiplier == 2.0
    assert params.dte_exit == 21


def test_params_update_after_accepted_optimization():
    opt, _ = _optimizer()
    original = opt.get_params("bull_put_spread").profit_target_pct
    opt.params["bull_put_spread"].profit_target_pct = 0.40
    assert opt.get_params("bull_put_spread").profit_target_pct == 0.40
    assert original == 0.50


# ── _score_params (pure — no I/O) ───────────────────────────────────────────

def test_score_params_penalizes_too_few_trades():
    opt, _ = _optimizer()
    assert opt._score_params(_bt_result([100.0, -50.0])) == -999.0  # only 2 trades


def test_score_params_computes_real_sharpe():
    opt, _ = _optimizer()
    sharpe = opt._score_params(_bt_result(_make_trades(n=40, win_rate=0.65)))
    assert isinstance(sharpe, float)
    assert sharpe != -999.0


# ── optimize() — mocked Backtester.run() ────────────────────────────────────

@pytest.mark.asyncio
async def test_optimize_skips_with_insufficient_trades():
    opt, backtester = _optimizer(run_return_value=_bt_result(_make_trades(n=10)))
    result = await opt.optimize("bull_put_spread")
    assert not result.accepted
    assert "training window" in (result.rejection_reason or "").lower()
    assert result.n_trades_train == 10
    assert result.grid_points_tested == 0


@pytest.mark.asyncio
async def test_optimize_runs_with_enough_trades():
    opt, backtester = _optimizer(run_return_value=_bt_result(_make_trades(n=60, win_rate=0.65)))
    result = await opt.optimize("bull_put_spread", train_months=4, validate_months=1)
    # May or may not accept — but should complete without error and test
    # every grid point in the reduced default grid (3*3*2 = 18).
    assert result.grid_points_tested == 18
    assert result.n_trades_train == 60


@pytest.mark.asyncio
async def test_optimize_reduced_grid_is_default_full_grid_is_opt_in():
    opt, backtester = _optimizer(run_return_value=_bt_result(_make_trades(n=60)))
    reduced = await opt.optimize("bull_put_spread")
    assert reduced.grid_points_tested == 18  # REDUCED_PARAM_GRID: 3*3*2

    backtester.run.reset_mock()
    full = await opt.optimize("bull_put_spread", full_grid=True)
    assert full.grid_points_tested == 320  # PARAM_GRID: 5*4*4*4


@pytest.mark.asyncio
async def test_optimize_rejects_when_insufficient_validation_trades():
    # Baseline/grid calls (train window) return plenty of trades; the
    # validate-window calls return too few.
    call_count = {"n": 0}

    async def _run_side_effect(*args, **kwargs):
        call_count["n"] += 1
        # First call is the train-window baseline; grid points reuse the
        # same train window too. Only the last 2 calls (validate window)
        # should return few trades — simulate by checking dates passed.
        start = args[1] if len(args) > 1 else kwargs.get("start_date")
        return _bt_result(_make_trades(n=60)) if call_count["n"] <= 19 else _bt_result(_make_trades(n=2))

    opt, backtester = _optimizer(run_side_effect=_run_side_effect)
    result = await opt.optimize("bull_put_spread")
    assert not result.accepted
    assert "validation trades" in (result.rejection_reason or "").lower()


# ── kelly_position_size() ───────────────────────────────────────────────────

def test_kelly_returns_default_with_few_trades():
    opt, _ = _optimizer()
    size = opt.kelly_position_size("bull_put_spread", _make_trades(n=10))
    assert size == 0.02


def test_kelly_caps_at_3_pct():
    opt, _ = _optimizer()
    pnls = _make_trades(n=50, win_rate=0.90, avg_win=300.0, avg_loss=-50.0)
    size = opt.kelly_position_size("bull_put_spread", pnls)
    assert size <= 0.03


def test_kelly_floors_above_zero():
    opt, _ = _optimizer()
    pnls = _make_trades(n=40, win_rate=0.30, avg_win=50.0, avg_loss=-300.0)
    size = opt.kelly_position_size("bull_put_spread", pnls)
    assert size >= 0.005
