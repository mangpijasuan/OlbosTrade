"""
Round-trip coverage for the execution_events persistence helpers in
trade_desk.py (_queue_pending_approval / _get_pending_approvals /
_resolve_pending_approval / _log_execution).

These replaced the in-memory _pending_approvals dict and _execution_log list,
which were wiped by every deploy/restart — the same class of bug as the
bracket-order ack race and the pending-order grace-period timer fixed earlier
this project. This file proves the DB-backed replacements build the right
ExecutionEvent rows and read them back correctly; test_trade_desk_routes.py
and test_scan_signal_routing.py cover the routing logic that calls these
helpers, with the helpers themselves mocked out.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.trade_desk import (
    _get_pending_approvals, _log_execution, _queue_pending_approval,
    _resolve_pending_approval,
)
from app.models.execution_event import ExecutionEvent


def _session(execute_results=None):
    """Fake AsyncSessionLocal()-produced session supporting the exact shape
    `async with AsyncSessionLocal() as session: async with session.begin(): ...`
    used by every helper in trade_desk.py."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=txn)
    session.add = MagicMock()
    if execute_results is not None:
        session.execute = AsyncMock(side_effect=execute_results)
    return session


@pytest.mark.asyncio
async def test_queue_pending_approval_persists_row():
    session = _session()
    signal = {"ticker": "SPY", "asset_type": "equity", "action": "BUY"}
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await _queue_pending_approval(signal)

    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert isinstance(row, ExecutionEvent)
    assert row.kind == "pending_approval"
    assert row.status == "pending"
    assert row.ticker == "SPY"
    assert row.asset_type == "equity"
    assert row.signal_id == signal["id"]          # helper assigns an id if missing
    assert row.payload is signal
    assert signal["status"] == "pending_approval"
    assert "queued_at" in signal


@pytest.mark.asyncio
async def test_queue_pending_approval_keeps_existing_id():
    session = _session()
    signal = {"id": "s-existing", "ticker": "QQQ"}
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await _queue_pending_approval(signal)
    assert session.add.call_args.args[0].signal_id == "s-existing"


@pytest.mark.asyncio
async def test_get_pending_approvals_returns_payloads_in_query_order():
    rows = [MagicMock(payload={"id": "s2", "ticker": "AMZN"}),
            MagicMock(payload={"id": "s1", "ticker": "NVDA"})]
    result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: rows)))
    session = _session([result])
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        out = await _get_pending_approvals()
    assert [p["ticker"] for p in out] == ["AMZN", "NVDA"]


@pytest.mark.asyncio
async def test_resolve_pending_approval_marks_resolved_and_returns_payload():
    row = MagicMock(payload={"id": "s1", "ticker": "SPY"}, status="pending")
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=row))
    session = _session([result])
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        payload = await _resolve_pending_approval("s1", "approved")
    assert payload == {"id": "s1", "ticker": "SPY"}
    assert row.status == "approved"


@pytest.mark.asyncio
async def test_resolve_pending_approval_returns_none_when_not_found():
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    session = _session([result])
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        payload = await _resolve_pending_approval("missing", "approved")
    assert payload is None


@pytest.mark.asyncio
async def test_log_execution_persists_row():
    session = _session()
    entry = {"signal_id": "s1", "ticker": "SPY", "asset_type": "equity", "result": "submitted"}
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await _log_execution(entry)

    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert row.kind == "execution"
    assert row.signal_id == "s1"
    assert row.status == "submitted"
    assert row.payload is entry


@pytest.mark.asyncio
async def test_log_execution_swallows_db_failure():
    """A DB failure recording an already-placed order must not raise — the
    trade already happened; losing the log entry gets a critical-level alert
    instead of an unhandled exception in the caller."""
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        await _log_execution({"ticker": "SPY", "result": "submitted"})  # no raise
