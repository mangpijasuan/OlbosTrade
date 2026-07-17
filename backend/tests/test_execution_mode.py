"""Tests for the ExecutionModeManager (Manual / Copilot / Autopilot + persistence).

Previously mode was persisted to /tmp/olbostrade_exec_mode.json inside the
container — wiped on every deploy/restart. Now it's a DB-backed row in
execution_events (kind="mode_change"), mirroring the kill switch's rehydrate()
pattern (kill_switch.py). These tests mock AsyncSessionLocal the same way
test_kill_switch.py does.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.execution_mode import ExecutionMode, ExecutionModeManager


def _session(execute_result=None):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=txn)
    session.add = MagicMock()
    if execute_result is not None:
        session.execute = AsyncMock(return_value=execute_result)
    return session


def test_enum_values():
    assert ExecutionMode.MANUAL.value == "manual"
    assert ExecutionMode.COPILOT.value == "copilot"
    assert ExecutionMode.AUTOPILOT.value == "autopilot"


def test_default_mode_before_rehydrate():
    mgr = ExecutionModeManager()
    assert mgr.mode == ExecutionMode.MANUAL


@pytest.mark.asyncio
async def test_set_mode_and_summary_flags():
    mgr = ExecutionModeManager()
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        s = await mgr.set_mode(ExecutionMode.AUTOPILOT)
    assert s["mode"] == "autopilot"
    assert s["auto_equity"] is True and s["auto_options"] is True
    assert s["needs_approval"] is False
    assert "description" in s and s["changed_by"] == "user"

    with patch("app.core.database.AsyncSessionLocal", return_value=_session()):
        s2 = await mgr.set_mode(ExecutionMode.COPILOT, by="tester")
    assert s2["needs_approval"] is True and s2["auto_equity"] is False
    assert s2["changed_by"] == "tester"

    s3 = mgr.summary()
    assert s3["mode"] == "copilot"


@pytest.mark.asyncio
async def test_set_mode_persists_row():
    mgr = ExecutionModeManager()
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await mgr.set_mode(ExecutionMode.AUTOPILOT, by="tester")
    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert row.kind == "mode_change"
    assert row.status == "autopilot"
    assert row.payload["changed_by"] == "tester"


@pytest.mark.asyncio
async def test_set_mode_persist_failure_is_non_fatal():
    mgr = ExecutionModeManager()
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        out = await mgr.set_mode(ExecutionMode.COPILOT)   # must not raise
    assert out["mode"] == "copilot"
    assert mgr.mode == ExecutionMode.COPILOT


@pytest.mark.asyncio
async def test_rehydrate_restores_last_mode():
    from datetime import datetime, timezone
    row = MagicMock(status="autopilot", created_at=datetime.now(timezone.utc),
                     payload={"changed_by": "tester"})
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=row))
    mgr = ExecutionModeManager()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(result)):
        await mgr.rehydrate()
    assert mgr.mode == ExecutionMode.AUTOPILOT
    assert mgr.summary()["changed_by"] == "tester"


@pytest.mark.asyncio
async def test_rehydrate_defaults_to_manual_when_no_history():
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    mgr = ExecutionModeManager()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(result)):
        await mgr.rehydrate()
    assert mgr.mode == ExecutionMode.MANUAL


@pytest.mark.asyncio
async def test_rehydrate_failure_defaults_to_manual():
    mgr = ExecutionModeManager()
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        await mgr.rehydrate()   # must not raise
    assert mgr.mode == ExecutionMode.MANUAL
