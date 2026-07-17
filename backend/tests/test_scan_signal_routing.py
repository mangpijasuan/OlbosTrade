"""Safety coverage for scan-panel signal routing (trade_desk.submit_scan_signal).

The key invariant: scan-driven signals NEVER auto-execute — not even in
AUTOPILOT — until the scan → execution path has full coverage. All modes queue
for approval / copilot; none reach _execute_signal. This test is the guard that
keeps that gate closed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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


def _req() -> ScanSignalRequest:
    return ScanSignalRequest(
        ticker="spy", action="SELL", entry_price=100.0,
        stop_price=95.0, target_price=110.0, kelly_fraction=0.2,
        source="options_scan_engine",
    )


async def test_autopilot_scan_signal_does_not_auto_execute(_queue_spy):
    """AUTOPILOT must NOT place a trade from a scan — it queues instead."""
    execution_mode_manager._mode = ExecutionMode.AUTOPILOT
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_approval"
    # signal is queued, not executed
    _queue_spy.assert_awaited_once()
    assert _queue_spy.await_args.args[0]["id"] == result["signal_id"]


async def test_manual_scan_signal_queues_for_approval(_queue_spy):
    execution_mode_manager._mode = ExecutionMode.MANUAL
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_approval"
    _queue_spy.assert_awaited_once()
    assert _queue_spy.await_args.args[0]["id"] == result["signal_id"]


async def test_copilot_scan_signal_goes_to_copilot_queue(_queue_spy):
    execution_mode_manager._mode = ExecutionMode.COPILOT
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_copilot"
    _queue_spy.assert_awaited_once()
    assert _queue_spy.await_args.args[0]["id"] == result["signal_id"]


async def test_ticker_is_normalized_uppercase(_queue_spy):
    execution_mode_manager._mode = ExecutionMode.MANUAL
    result = await submit_scan_signal(_req())
    queued = _queue_spy.await_args.args[0]
    assert queued["ticker"] == "SPY"
