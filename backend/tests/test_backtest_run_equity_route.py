"""
Tests for POST /api/backtest/run-equity — see test_backtester_run_equity.py
for the underlying Backtester.run_equity() walk-forward logic tests.

Route-level: this module transitively imports app.models.backtest_result,
which trips the local py3.9 SQLAlchemy-annotation wall — runs on CI
(py3.11) as the source of truth, matching the rest of this test suite's
established constraint.
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest


def _capturing_create_task(bucket: list):
    """Replaces asyncio.create_task so the test can explicitly await the
    background task instead of guessing how many event-loop turns it needs."""
    def _create(coro):
        task = asyncio.ensure_future(coro)
        bucket.append(task)
        return task
    return _create


def _fake_result(ticker: str):
    from app.services.backtester import BacktestResult, BacktestTrade
    from app.utils.metrics import PerformanceMetrics

    trade = BacktestTrade(
        strategy="equity", underlying=ticker,
        entry_date=date(2024, 1, 3), exit_date=date(2024, 1, 10),
        direction="BUY", entry_price=100.0, exit_price=104.0,
        stop_price=96.0, target_price=108.0,
        pnl=400.0, pnl_pct=0.016, exit_reason="target",
        signal_score=0.75, commission_paid=1.0, contracts=100, hold_days=7,
    )
    metrics = PerformanceMetrics(
        total_return_pct=0.016, annualized_return_pct=0.4, sharpe_ratio=1.1,
        sortino_ratio=1.3, calmar_ratio=1.0, max_drawdown_pct=0.02,
        max_drawdown_duration_days=3, win_rate=1.0, profit_factor=99.0,
        total_trades=1, winning_trades=1, losing_trades=0,
        avg_win=400.0, avg_loss=0.0, avg_hold_days=7.0,
        commission_drag_pct=0.0001, expectancy=400.0,
    )
    return BacktestResult(
        strategy=f"equity:{ticker}", start_date=date(2024, 1, 1), end_date=date(2024, 6, 30),
        starting_capital=25000.0, ending_capital=25400.0,
        trades=[trade], metrics=metrics, equity_curve=[25000.0, 25400.0],
    )


@pytest.mark.asyncio
async def test_run_equity_route_rejects_blank_ticker():
    from app.api.routes.backtest import run_equity_backtest, EquityBacktestRunRequest
    from fastapi import HTTPException

    req = EquityBacktestRunRequest(ticker="   ", start_date="2024-01-01", end_date="2024-06-30")
    with pytest.raises(HTTPException) as exc_info:
        await run_equity_backtest(req)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_run_equity_route_queues_then_completes():
    from app.api.routes.backtest import run_equity_backtest, EquityBacktestRunRequest, _runs

    req = EquityBacktestRunRequest(ticker="aapl", start_date="2024-01-01", end_date="2024-06-30")
    tasks: list = []

    with patch("app.api.routes.backtest._persist_run", new=AsyncMock()), \
         patch("app.api.routes.backtest.asyncio.create_task", new=_capturing_create_task(tasks)), \
         patch("app.broker.broker_factory.get_broker", return_value=object()), \
         patch("app.services.data_fetcher.DataFetcher", return_value=object()), \
         patch("app.services.backtester.Backtester.run_equity",
               new=AsyncMock(return_value=_fake_result("AAPL"))):
        resp = await run_equity_backtest(req)

        assert resp["status"] == "queued"
        assert resp["strategy"] == "equity:AAPL"
        assert resp["ticker"] == "AAPL"
        run_id = resp["run_id"]

        assert len(tasks) == 1
        await tasks[0]

        completed = _runs[run_id]
        assert completed["status"] == "completed"
        assert completed["strategy"] == "equity:AAPL"
        assert completed["total_trades"] == 1
        assert len(completed["trades"]) == 1
        t = completed["trades"][0]
        assert t["direction"] == "BUY"
        assert t["entry_price"] == 100.0
        assert t["shares"] == 100
        assert t["exit_reason"] == "target"


@pytest.mark.asyncio
async def test_run_equity_route_marks_failed_on_exception():
    from app.api.routes.backtest import run_equity_backtest, EquityBacktestRunRequest, _runs

    req = EquityBacktestRunRequest(ticker="ZZZZ", start_date="2024-01-01", end_date="2024-06-30")
    tasks: list = []

    with patch("app.api.routes.backtest._persist_run", new=AsyncMock()), \
         patch("app.api.routes.backtest.asyncio.create_task", new=_capturing_create_task(tasks)), \
         patch("app.broker.broker_factory.get_broker", return_value=object()), \
         patch("app.services.data_fetcher.DataFetcher", return_value=object()), \
         patch("app.services.backtester.Backtester.run_equity",
               new=AsyncMock(side_effect=ValueError("No OHLCV data returned for ZZZZ"))):
        resp = await run_equity_backtest(req)
        run_id = resp["run_id"]
        await tasks[0]

        assert _runs[run_id]["status"] == "failed"
        assert "ZZZZ" in _runs[run_id]["error"]
