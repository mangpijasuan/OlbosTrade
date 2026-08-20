"""Safety coverage for scan-panel signal routing (trade_desk.submit_scan_signal).

The key invariant: scan-driven signals NEVER auto-execute — not even in
AUTOPILOT — until the scan → execution path has full coverage. All modes queue
for approval / copilot; none reach _execute_signal. This test is the guard that
keeps that gate closed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import app.api.routes.trade_desk as td
from app.api.routes.trade_desk import ScanSignalRequest, submit_scan_signal
from app.services.execution_mode import ExecutionMode, execution_mode_manager


@pytest.fixture(autouse=True)
def _clean_state():
    execution_mode_manager._mode = ExecutionMode.MANUAL
    yield
    execution_mode_manager._mode = ExecutionMode.MANUAL


@pytest.fixture(autouse=True)
def _queue_spy():
    """Scan-signal routing only needs to prove *whether* a signal was queued for
    approval, not how the queue is persisted — that's covered separately in
    test_execution_events_helpers.py. Patch the persistence call to a spy."""
    with patch.object(td, "_queue_pending_approval", new=AsyncMock()) as mock:
        yield mock


def _equity_req(**overrides) -> ScanSignalRequest:
    data = dict(
        ticker="spy",
        action="BUY",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        kelly_fraction=0.2,
        source="equity_scan_engine",
        asset_type="equity",
    )
    data.update(overrides)
    return ScanSignalRequest(**data)


def _options_req(**overrides) -> ScanSignalRequest:
    data = dict(
        ticker="spy",
        action="SELL",
        entry_price=150.0,
        stop_price=0.0,
        target_price=225.0,
        kelly_fraction=0.2,
        source="options_scan_engine",
        asset_type="options",
        strategy="bull_put_spread",
        quantity=1,
        spread={
            "expiration": "2026-09-18",
            "short_strike": 450,
            "long_strike": 445,
            "option_type": "put",
            "net_credit": 150.0,
            "max_loss": 350.0,
        },
    )
    data.update(overrides)
    return ScanSignalRequest(**data)


async def test_autopilot_scan_signal_does_not_auto_execute(_queue_spy):
    """AUTOPILOT must NOT place a trade from a scan — it queues instead."""
    execution_mode_manager._mode = ExecutionMode.AUTOPILOT
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_equity_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_approval"
    _queue_spy.assert_awaited_once()
    assert _queue_spy.await_args.args[0]["id"] == result["signal_id"]


async def test_manual_scan_signal_queues_for_approval(_queue_spy):
    execution_mode_manager._mode = ExecutionMode.MANUAL
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_equity_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_approval"
    _queue_spy.assert_awaited_once()
    assert _queue_spy.await_args.args[0]["id"] == result["signal_id"]


async def test_copilot_scan_signal_goes_to_copilot_queue(_queue_spy):
    execution_mode_manager._mode = ExecutionMode.COPILOT
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_equity_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_copilot"
    _queue_spy.assert_awaited_once()
    assert _queue_spy.await_args.args[0]["id"] == result["signal_id"]


async def test_ticker_is_normalized_uppercase(_queue_spy):
    execution_mode_manager._mode = ExecutionMode.MANUAL
    result = await submit_scan_signal(_equity_req())
    queued = _queue_spy.await_args.args[0]
    assert queued["ticker"] == "SPY"
    assert result["signal_id"]


async def test_equity_shares_reach_queued_trade_plan(_queue_spy):
    """Composer/scan size must land in trade_plan so approve does not default to 1."""
    execution_mode_manager._mode = ExecutionMode.COPILOT
    req = _equity_req(
        ticker="AAPL",
        entry_price=150.0,
        stop_price=145.0,
        target_price=160.0,
        shares=25,
        source="equity_desk_composer",
    )
    result = await submit_scan_signal(req)
    queued = _queue_spy.await_args.args[0]
    assert result["shares"] == 25
    assert queued["asset_type"] == "equity"
    assert queued["trade_plan"]["shares"] == 25
    assert queued["trade_plan"]["entry_price"] == 150.0


async def test_options_scan_queues_with_spread(_queue_spy):
    execution_mode_manager._mode = ExecutionMode.MANUAL
    result = await submit_scan_signal(_options_req())
    queued = _queue_spy.await_args.args[0]
    assert result["status"] == "pending_approval"
    assert queued["asset_type"] == "options"
    assert queued["spread"]["short_strike"] == 450
    assert queued["strategy"] == "bull_put_spread"


async def test_options_scan_engine_without_spread_is_rejected(_queue_spy):
    """Equity-shaped options_scan_engine bodies must not enter the queue."""
    with pytest.raises(HTTPException) as exc:
        await submit_scan_signal(
            ScanSignalRequest(
                ticker="SPY",
                action="SELL",
                entry_price=100.0,
                stop_price=0.0,
                target_price=150.0,
                source="options_scan_engine",
            )
        )
    assert exc.value.status_code == 400
    assert "spread" in str(exc.value.detail).lower()
    _queue_spy.assert_not_awaited()
