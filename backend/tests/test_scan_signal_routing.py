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
    td._pending_approvals.clear()
    td._execution_log.clear()
    execution_mode_manager.set_mode(ExecutionMode.MANUAL)
    yield
    td._pending_approvals.clear()
    td._execution_log.clear()
    execution_mode_manager.set_mode(ExecutionMode.MANUAL)


def _req() -> ScanSignalRequest:
    return ScanSignalRequest(
        ticker="spy", action="SELL", entry_price=100.0,
        stop_price=95.0, target_price=110.0, kelly_fraction=0.2,
        source="options_scan_engine",
    )


async def test_autopilot_scan_signal_does_not_auto_execute():
    """AUTOPILOT must NOT place a trade from a scan — it queues instead."""
    execution_mode_manager.set_mode(ExecutionMode.AUTOPILOT)
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_approval"
    # signal is queued, not executed
    assert result["signal_id"] in td._pending_approvals
    assert td._execution_log == []


async def test_manual_scan_signal_queues_for_approval():
    execution_mode_manager.set_mode(ExecutionMode.MANUAL)
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_approval"
    assert result["signal_id"] in td._pending_approvals


async def test_copilot_scan_signal_goes_to_copilot_queue():
    execution_mode_manager.set_mode(ExecutionMode.COPILOT)
    with patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock:
        result = await submit_scan_signal(_req())

    exec_mock.assert_not_called()
    assert result["status"] == "pending_copilot"
    assert result["signal_id"] in td._pending_approvals


async def test_ticker_is_normalized_uppercase():
    execution_mode_manager.set_mode(ExecutionMode.MANUAL)
    result = await submit_scan_signal(_req())
    queued = td._pending_approvals[result["signal_id"]]
    assert queued["ticker"] == "SPY"
