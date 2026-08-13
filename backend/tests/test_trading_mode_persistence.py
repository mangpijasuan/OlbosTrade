"""Tests for TradingModeManager's DB-backed persistence.

Previously mode was persisted to /tmp/olbostrade_trading_mode.json inside the
container — wiped on every deploy/restart, so the chosen mode (e.g.
Aggressive) silently reset to Balanced on every restart. Confirmed in
production. Now it's a DB-backed row in execution_events
(kind="trading_mode_change"), mirroring execution_mode.py's already-fixed
pattern (test_execution_mode.py). These tests mock AsyncSessionLocal the same
way test_execution_mode.py does.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.trading_mode import TradingModeManager, TradingModeType


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


def test_default_mode_before_rehydrate():
    mgr = TradingModeManager()
    assert mgr.current.active_mode == TradingModeType.BALANCED
    assert mgr.current.activated_by == "default"


@pytest.mark.asyncio
async def test_set_mode_persists_row():
    mgr = TradingModeManager()
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await mgr.set_mode(TradingModeType.AGGRESSIVE, activated_by="tester")
    assert mgr.current.active_mode == TradingModeType.AGGRESSIVE
    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert row.kind == "trading_mode_change"
    assert row.status == "aggressive"
    assert row.payload["activated_by"] == "tester"


@pytest.mark.asyncio
async def test_set_mode_persist_failure_is_non_fatal():
    mgr = TradingModeManager()
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        state = await mgr.set_mode(TradingModeType.AGGRESSIVE)   # must not raise
    assert state.active_mode == TradingModeType.AGGRESSIVE
    assert mgr.current.active_mode == TradingModeType.AGGRESSIVE


@pytest.mark.asyncio
async def test_rehydrate_restores_last_mode():
    from datetime import datetime, timezone
    row = MagicMock(status="aggressive", created_at=datetime.now(timezone.utc),
                     payload={"activated_by": "tester"})
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=row))
    mgr = TradingModeManager()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(result)):
        await mgr.rehydrate()
    assert mgr.current.active_mode == TradingModeType.AGGRESSIVE
    assert mgr.current.activated_by == "tester"


@pytest.mark.asyncio
async def test_rehydrate_defaults_to_balanced_when_no_history():
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    mgr = TradingModeManager()
    with patch("app.core.database.AsyncSessionLocal", return_value=_session(result)):
        await mgr.rehydrate()
    assert mgr.current.active_mode == TradingModeType.BALANCED


@pytest.mark.asyncio
async def test_rehydrate_failure_defaults_to_balanced():
    mgr = TradingModeManager()
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        await mgr.rehydrate()   # must not raise
    assert mgr.current.active_mode == TradingModeType.BALANCED


@pytest.mark.asyncio
async def test_auto_downgrade_persists_and_awaits():
    mgr = TradingModeManager()
    await mgr.set_mode(TradingModeType.AGGRESSIVE)
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        state = await mgr.auto_downgrade("daily loss limit breached")
    assert state.active_mode == TradingModeType.CONSERVATIVE
    assert state.activated_by == "auto_capital_preservation"
