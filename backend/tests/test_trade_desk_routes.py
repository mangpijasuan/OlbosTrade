"""Coverage for trade_desk route handlers, portfolio-state read, dispatcher,
and the options execution branch."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.api.routes.trade_desk as td
from app.api.routes.trade_desk import (
    ManualTradeRequest, KillSwitchRequest, SetExecutionModeRequest, RiskGateError,
    _execute_signal, _fetch_portfolio_state, approve_signal, get_execution_log,
    get_execution_mode, get_kill_switch, get_pending, handle_signal, manual_trade,
    reject_signal, set_execution_mode, set_kill_switch,
)
from app.services.execution_mode import ExecutionMode
from app.services.guardrails import PortfolioState


@pytest.fixture(autouse=True)
def _market_open():
    with patch("app.utils.market_hours.is_market_open", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _clear_state():
    td._pending_approvals.clear()
    td._execution_log.clear()
    yield


def _clean():
    return PortfolioState(current_value=100_000.0, starting_capital=100_000.0,
                          daily_pnl=0.0, weekly_pnl=0.0, monthly_pnl=0.0,
                          consecutive_losses=0, trades_today=0)


# ── _fetch_portfolio_state ───────────────────────────────────────────────────────
def _pf_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalar = MagicMock(return_value=0)
    result.scalars.return_value = MagicMock(all=lambda: [])
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_fetch_portfolio_state_success():
    broker = MagicMock()
    broker.get_account_summary = AsyncMock(return_value=MagicMock(net_liquidation=123456.0))
    with patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_pf_session()):
        st = await _fetch_portfolio_state()
    assert st.current_value == 123456.0
    assert st.trades_today == 0 and st.consecutive_losses == 0


@pytest.mark.asyncio
async def test_fetch_portfolio_state_counts_consecutive_losses():
    session = _pf_session()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar=MagicMock(return_value=2),
        scalars=lambda: MagicMock(all=lambda: [-5.0, -3.0, 10.0, -1.0])))
    with patch("app.broker.broker_factory.get_broker", side_effect=Exception("no broker")), \
         patch("app.core.database.AsyncSessionLocal", return_value=session):
        st = await _fetch_portfolio_state()
    assert st.consecutive_losses == 2     # stops at the first non-loss
    from app.core.config import settings as _cfg
    assert st.current_value == _cfg.starting_capital   # broker failed → config fallback


@pytest.mark.asyncio
async def test_fetch_portfolio_state_fail_closed():
    with patch("app.broker.broker_factory.get_broker", side_effect=Exception("x")), \
         patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        with pytest.raises(RiskGateError):
            await _fetch_portfolio_state()


# ── kill switch + execution mode endpoints ────────────────────────────────────────
@pytest.mark.asyncio
async def test_kill_switch_get_set():
    td._kill_switch.clear()
    assert (await get_kill_switch())["engaged"] is False
    with patch.object(td.kill_switch_service, "engage", new=AsyncMock()), \
         patch.object(td.kill_switch_service, "reset", new=AsyncMock()):
        out = await set_kill_switch(KillSwitchRequest(engaged=True))
        assert out["engaged"] is True
        await set_kill_switch(KillSwitchRequest(engaged=False))
    td._kill_switch.clear()


@pytest.mark.asyncio
async def test_execution_mode_get_set_and_invalid():
    out = await get_execution_mode()
    assert "mode" in out
    ok = await set_execution_mode(SetExecutionModeRequest(mode="copilot"))
    assert ok["mode"] == "copilot"
    with pytest.raises(Exception):
        await set_execution_mode(SetExecutionModeRequest(mode="bogus"))
    await set_execution_mode(SetExecutionModeRequest(mode="manual"))


# ── pending / approve / reject ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pending_lists_queue():
    td._pending_approvals["s1"] = {"id": "s1", "ticker": "SPY", "queued_at": "2026-01-01"}
    out = await get_pending()
    assert out["count"] == 1 and out["pending"][0]["ticker"] == "SPY"


@pytest.mark.asyncio
async def test_approve_signal_executes():
    td._pending_approvals["s1"] = {"id": "s1", "ticker": "SPY", "asset_type": "equity"}
    with patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "submitted", "ticker": "SPY"})):
        out = await approve_signal("s1")
    assert out["result"] == "submitted"
    assert "s1" not in td._pending_approvals
    assert td._execution_log[0]["approved_by"] == "user"


@pytest.mark.asyncio
async def test_approve_signal_not_found():
    with pytest.raises(Exception):
        await approve_signal("missing")


@pytest.mark.asyncio
async def test_reject_signal():
    td._pending_approvals["s2"] = {"id": "s2", "ticker": "QQQ", "action": "BUY"}
    out = await reject_signal("s2")
    assert out["result"] == "rejected" and out["rejected_by"] == "user"
    assert "s2" not in td._pending_approvals


@pytest.mark.asyncio
async def test_reject_signal_not_found():
    with pytest.raises(Exception):
        await reject_signal("nope")


# ── manual trade + execution log ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_manual_trade_success_logs():
    with patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "submitted", "ticker": "AAPL"})):
        out = await manual_trade(ManualTradeRequest(ticker="aapl", action="buy", shares=5))
    assert out["result"] == "submitted"
    assert len(td._execution_log) == 1


@pytest.mark.asyncio
async def test_manual_trade_error_raises():
    with patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "error", "error": "boom"})):
        with pytest.raises(Exception):
            await manual_trade(ManualTradeRequest(ticker="aapl", action="buy", shares=5))


@pytest.mark.asyncio
async def test_execution_log_limit():
    td._execution_log.extend([{"i": i} for i in range(5)])
    out = await get_execution_log(limit=3)
    assert len(out["log"]) == 3 and out["total"] == 5


# ── handle_signal dispatcher ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_handle_signal_manual_noop():
    td.execution_mode_manager.set_mode(ExecutionMode.MANUAL)
    await handle_signal({"id": "x", "ticker": "SPY"})   # no error, nothing queued
    assert td._pending_approvals == {}


@pytest.mark.asyncio
async def test_handle_signal_copilot_queues():
    td.execution_mode_manager.set_mode(ExecutionMode.COPILOT)
    await handle_signal({"id": "c1", "ticker": "SPY"})
    assert "c1" in td._pending_approvals
    assert td._pending_approvals["c1"]["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_handle_signal_autopilot_executes_and_logs_block():
    td.execution_mode_manager.set_mode(ExecutionMode.AUTOPILOT)
    with patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "blocked", "reason": "kill_switch"})):
        await handle_signal({"id": "a1", "ticker": "SPY"})
    assert td._execution_log[0]["result"] == "blocked"
    td.execution_mode_manager.set_mode(ExecutionMode.MANUAL)


# ── options execution branch of _execute_signal ───────────────────────────────────
def _options_signal():
    return {
        "id": "o1", "ticker": "SPY", "action": "SELL", "asset_type": "options",
        "strategy": "bull_put_spread", "quantity": 1, "confidence": 0.9, "pop": 0.85,
        "signal_score": 0.85, "iv_rank": 45.0, "regime": "normal_mean_revert",
        "spread": {"expiration": "2026-09-18", "short_strike": 450, "long_strike": 445,
                   "option_type": "put", "net_credit": 150.0, "max_loss": 350.0},
    }


def _dup_session(existing=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock(first=lambda: existing))
    return session


@pytest.mark.asyncio
async def test_options_execution_submits_and_records():
    broker = MagicMock()
    broker.place_order = AsyncMock(return_value=MagicMock(order_id="ORD-9", status="submitted"))
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.api.routes.trade_desk._strategy_health_for", new=AsyncMock(return_value=None)), \
         patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(None)), \
         patch("app.services.trade_recorder.trade_recorder.record_fill",
               new=AsyncMock(return_value="trade-1")):
        res = await _execute_signal(_options_signal(), approved_by="autopilot")
    assert res["result"] == "submitted" and res["asset_type"] == "options"
    broker.place_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_options_execution_zero_size_skipped():
    sig = _options_signal()
    sig["quantity"] = 0
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(None)), \
         patch("app.broker.broker_factory.get_broker", return_value=MagicMock()):
        res = await _execute_signal(sig, approved_by="manual")
    assert res["result"] == "skipped" and "zero_size" in res["reason"]


@pytest.mark.asyncio
async def test_market_closed_blocks_order():
    with patch("app.utils.market_hours.is_market_open", return_value=False), \
         patch("app.utils.market_hours.market_status",
               return_value={"reason": "weekend", "now_et": "Sat 10:00"}), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False):
        res = await _execute_signal(_options_signal(), approved_by="manual")
    assert res["result"] == "blocked" and "market_closed" in res["reason"]


@pytest.mark.asyncio
async def test_options_record_failure_still_submits():
    # broker fills but DB record fails (None) → still 'submitted', critical-log path
    broker = MagicMock()
    broker.place_order = AsyncMock(return_value=MagicMock(order_id="ORD-X", status="submitted"))
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(None)), \
         patch("app.services.trade_recorder.trade_recorder.record_fill",
               new=AsyncMock(return_value=None)):
        res = await _execute_signal(_options_signal(), approved_by="manual")
    assert res["result"] == "submitted"


@pytest.mark.asyncio
async def test_duplicate_open_trade_skipped():
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(existing=("trade-x",))), \
         patch("app.broker.broker_factory.get_broker", return_value=MagicMock()):
        res = await _execute_signal(_options_signal(), approved_by="manual")
    assert res["result"] == "skipped" and "already_open" in res["reason"]
