"""Coverage for trade_desk route handlers, portfolio-state read, dispatcher,
and the options execution branch."""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.api.routes.trade_desk as td
from app.api.routes.trade_desk import (
    ClosePositionRequest, ManualTradeRequest, KillSwitchRequest, SetExecutionModeRequest,
    RiskGateError, _execute_signal, _fetch_portfolio_state, approve_signal,
    close_position, get_execution_log, get_execution_mode, get_kill_switch,
    get_pending, handle_signal, manual_trade, reject_signal, set_execution_mode,
    set_kill_switch,
)
from app.services.execution_mode import ExecutionMode
from app.services.guardrails import PortfolioState


@pytest.fixture(autouse=True)
def _market_open():
    with patch("app.utils.market_hours.is_market_open", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _account_guard_ok():
    # The account-mode guard is exercised in test_account_guard.py; here it passes
    # by default so execution-path tests reach the broker submission stage.
    with patch("app.services.account_guard.verify_account_mode",
               new=AsyncMock(return_value=(True, "account DU-test (paper)"))):
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
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=txn)
    session.add = MagicMock()

    out = await get_execution_mode()
    assert "mode" in out
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        ok = await set_execution_mode(SetExecutionModeRequest(mode="copilot"))
        assert ok["mode"] == "copilot"
        with pytest.raises(Exception):
            await set_execution_mode(SetExecutionModeRequest(mode="bogus"))
        await set_execution_mode(SetExecutionModeRequest(mode="manual"))


# ── pending / approve / reject ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pending_lists_queue():
    with patch.object(td, "_get_pending_approvals",
                      new=AsyncMock(return_value=[{"id": "s1", "ticker": "SPY", "queued_at": "2026-01-01"}])):
        out = await get_pending()
    assert out["count"] == 1 and out["pending"][0]["ticker"] == "SPY"


@pytest.mark.asyncio
async def test_approve_signal_executes():
    with patch.object(td, "_resolve_pending_approval",
                      new=AsyncMock(return_value={"id": "s1", "ticker": "SPY", "asset_type": "equity"})), \
         patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "submitted", "ticker": "SPY"})), \
         patch.object(td, "_log_execution", new=AsyncMock()) as log_mock:
        out = await approve_signal("s1")
    assert out["result"] == "submitted"
    log_mock.assert_awaited_once()
    assert log_mock.await_args.args[0]["approved_by"] == "user"


@pytest.mark.asyncio
async def test_approve_signal_not_found():
    with patch.object(td, "_resolve_pending_approval", new=AsyncMock(return_value=None)):
        with pytest.raises(Exception):
            await approve_signal("missing")


@pytest.mark.asyncio
async def test_reject_signal():
    with patch.object(td, "_resolve_pending_approval",
                      new=AsyncMock(return_value={"id": "s2", "ticker": "QQQ", "action": "BUY"})), \
         patch.object(td, "_log_execution", new=AsyncMock()) as log_mock:
        out = await reject_signal("s2")
    assert out["result"] == "rejected" and out["rejected_by"] == "user"
    log_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_signal_not_found():
    with patch.object(td, "_resolve_pending_approval", new=AsyncMock(return_value=None)):
        with pytest.raises(Exception):
            await reject_signal("nope")


# ── manual trade + execution log ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_manual_trade_success_logs():
    with patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "submitted", "ticker": "AAPL"})), \
         patch.object(td, "_log_execution", new=AsyncMock()) as log_mock:
        out = await manual_trade(ManualTradeRequest(ticker="aapl", action="buy", shares=5))
    assert out["result"] == "submitted"
    log_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_trade_error_raises():
    with patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "error", "error": "boom"})):
        with pytest.raises(Exception):
            await manual_trade(ManualTradeRequest(ticker="aapl", action="buy", shares=5))


# ── close_position (manual close, separate from _execute_signal) ──────────────

def _fake_trade_session(trade):
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=trade))
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=result)
    return session


def _open_trade(spread_type="equity_long", status="open", quantity=10):
    t = MagicMock()
    t.id = "11111111-1111-1111-1111-111111111111"
    t.status = status
    t.spread_type = spread_type
    t.underlying = "AAPL"
    t.quantity = quantity
    return t


@pytest.mark.asyncio
async def test_close_position_invalid_trade_id_raises():
    with pytest.raises(Exception):
        await close_position(ClosePositionRequest(trade_id="not-a-uuid"))


@pytest.mark.asyncio
async def test_close_position_not_found_raises():
    session = _fake_trade_session(None)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        with pytest.raises(Exception):
            await close_position(ClosePositionRequest(
                trade_id="11111111-1111-1111-1111-111111111111"))


@pytest.mark.asyncio
async def test_close_position_already_closed_raises():
    session = _fake_trade_session(_open_trade(status="closed"))
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        with pytest.raises(Exception):
            await close_position(ClosePositionRequest(
                trade_id="11111111-1111-1111-1111-111111111111"))


@pytest.mark.asyncio
async def test_close_position_options_not_yet_supported_raises():
    session = _fake_trade_session(_open_trade(spread_type="put"))
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        with pytest.raises(Exception):
            await close_position(ClosePositionRequest(
                trade_id="11111111-1111-1111-1111-111111111111"))


@pytest.mark.asyncio
async def test_close_position_long_submits_sell_and_cancels_bracket():
    """A closing order must never go through _execute_signal's duplicate
    guard — this test proves it's never called — and equity_long closes
    with SELL, not BUY."""
    session = _fake_trade_session(_open_trade(spread_type="equity_long", quantity=10))
    broker = MagicMock()
    broker.cancel_open_orders = AsyncMock(return_value=2)
    broker.place_equity_order = AsyncMock(return_value=MagicMock(
        status="filled", order_id="ord-1", fill_price=101.5,
    ))
    with patch("app.core.database.AsyncSessionLocal", return_value=session), \
         patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch.object(td, "_execute_signal", new=AsyncMock()) as exec_mock, \
         patch.object(td, "_log_execution", new=AsyncMock()), \
         patch("app.services.trade_recorder.trade_recorder.record_exit",
               new=AsyncMock(return_value=True)) as record_mock:
        out = await close_position(ClosePositionRequest(
            trade_id="11111111-1111-1111-1111-111111111111"))

    exec_mock.assert_not_called()
    broker.cancel_open_orders.assert_awaited_once_with("AAPL")
    broker.place_equity_order.assert_awaited_once()
    assert broker.place_equity_order.await_args.kwargs["side"] == "SELL"
    assert broker.place_equity_order.await_args.kwargs["qty"] == 10
    record_mock.assert_awaited_once()
    assert record_mock.await_args.kwargs["cost_to_close"] == 101.5
    assert record_mock.await_args.kwargs["exit_reason"] == "manual"
    assert out["action"] == "SELL"
    assert out["cancelled_open_orders"] == 2


@pytest.mark.asyncio
async def test_close_position_short_submits_buy():
    session = _fake_trade_session(_open_trade(spread_type="equity_short", quantity=5))
    broker = MagicMock()
    broker.cancel_open_orders = AsyncMock(return_value=0)
    broker.place_equity_order = AsyncMock(return_value=MagicMock(
        status="submitted", order_id="ord-2", fill_price=None,
    ))
    with patch("app.core.database.AsyncSessionLocal", return_value=session), \
         patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch.object(td, "_log_execution", new=AsyncMock()):
        out = await close_position(ClosePositionRequest(
            trade_id="11111111-1111-1111-1111-111111111111"))

    assert broker.place_equity_order.await_args.kwargs["side"] == "BUY"
    assert out["status"] == "submitted"


@pytest.mark.asyncio
async def test_close_position_broker_rejection_raises():
    session = _fake_trade_session(_open_trade())
    broker = MagicMock()
    broker.cancel_open_orders = AsyncMock(return_value=0)
    broker.place_equity_order = AsyncMock(return_value=MagicMock(
        status="rejected", order_id=None, fill_price=None,
    ))
    with patch("app.core.database.AsyncSessionLocal", return_value=session), \
         patch("app.broker.broker_factory.get_broker", return_value=broker):
        with pytest.raises(Exception):
            await close_position(ClosePositionRequest(
                trade_id="11111111-1111-1111-1111-111111111111"))


@pytest.mark.asyncio
async def test_execution_log_limit():
    rows = [MagicMock(payload={"i": i}) for i in range(3)]
    list_result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: rows)))
    count_result = MagicMock(scalar_one=MagicMock(return_value=5))
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(side_effect=[list_result, count_result])
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        out = await get_execution_log(limit=3)
    assert len(out["log"]) == 3 and out["total"] == 5


# ── handle_signal dispatcher ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_handle_signal_manual_noop():
    td.execution_mode_manager._mode = ExecutionMode.MANUAL
    with patch.object(td, "_queue_pending_approval", new=AsyncMock()) as queue_mock:
        await handle_signal({"id": "x", "ticker": "SPY"})   # no error, nothing queued
    queue_mock.assert_not_called()


@pytest.mark.asyncio
async def test_handle_signal_copilot_queues():
    td.execution_mode_manager._mode = ExecutionMode.COPILOT
    with patch.object(td, "_queue_pending_approval", new=AsyncMock()) as queue_mock:
        signal = {"id": "c1", "ticker": "SPY"}
        await handle_signal(signal)
    queue_mock.assert_awaited_once_with(signal)
    td.execution_mode_manager._mode = ExecutionMode.MANUAL


@pytest.mark.asyncio
async def test_handle_signal_autopilot_executes_and_logs_block():
    td.execution_mode_manager._mode = ExecutionMode.AUTOPILOT
    with patch.object(td, "_execute_signal",
                      new=AsyncMock(return_value={"result": "blocked", "reason": "kill_switch"})), \
         patch.object(td, "_log_execution", new=AsyncMock()) as log_mock:
        await handle_signal({"id": "a1", "ticker": "SPY"})
    log_mock.assert_awaited_once()
    assert log_mock.await_args.args[0]["result"] == "blocked"
    td.execution_mode_manager._mode = ExecutionMode.MANUAL


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
    """Mock DB session for Stage 3 duplicate guard.

    `existing` may be:
      - None / [] → no open trades
      - a Trade-like object or list of them
      - legacy ``("trade-id",)`` → synthesize an open SPY options trade
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    if existing is None or existing == []:
        rows = []
    elif (
        isinstance(existing, tuple)
        and existing
        and not hasattr(existing[0], "underlying")
    ):
        t = MagicMock()
        t.id = existing[0]
        t.underlying = "SPY"
        t.spread_type = "bull_put_spread"
        t.strategy = "bull_put_spread"
        t.status = "open"
        rows = [t]
    elif isinstance(existing, (list, tuple)):
        rows = list(existing)
    else:
        rows = [existing]
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: rows)
    result.first = MagicMock(return_value=rows[0] if rows else None)
    session.execute = AsyncMock(return_value=result)
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
async def test_options_place_order_timeout_records_pending_not_lost():
    """The coordinator's wait_for can time out while the real IBKR call
    (shielded, still running) later fills — this must not be a silent lost
    fill: a pending Trade row has to get written so _poll_fills() can later
    promote or cancel it, and the caller must see an honest result instead
    of a generic error."""
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.broker.broker_factory.get_broker", return_value=MagicMock()), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(None)), \
         patch.object(td.ibkr_coordinator, "submit",
                      new=AsyncMock(side_effect=asyncio.TimeoutError("timed out"))), \
         patch("app.services.trade_recorder.trade_recorder.record_fill",
               new=AsyncMock(return_value="trade-pending-1")) as record_mock:
        res = await _execute_signal(_options_signal(), approved_by="manual")

    assert res["result"] == "pending_confirmation"
    assert res["asset_type"] == "options"
    record_mock.assert_awaited_once()
    assert record_mock.await_args.kwargs["status"] == "pending"
    assert record_mock.await_args.kwargs["dispatch_id"] == "o1"


@pytest.mark.asyncio
async def test_options_place_order_timeout_and_record_failure_logs_critical():
    """Belt-and-suspenders: even the pending-row write can fail (DB down) —
    must not raise, just log critical, since a real order may be in flight
    at the broker with zero remaining trace of it."""
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.broker.broker_factory.get_broker", return_value=MagicMock()), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(None)), \
         patch.object(td.ibkr_coordinator, "submit",
                      new=AsyncMock(side_effect=asyncio.TimeoutError("timed out"))), \
         patch("app.services.trade_recorder.trade_recorder.record_fill",
               new=AsyncMock(return_value=None)):
        res = await _execute_signal(_options_signal(), approved_by="manual")

    assert res["result"] == "pending_confirmation"


@pytest.mark.asyncio
async def test_equity_place_order_timeout_records_pending_not_lost():
    broker = MagicMock()
    broker.get_latest_quote = AsyncMock(return_value=MagicMock(ask_price=150.5, bid_price=150.0))
    sig = _equity_signal(source="equity_desk_composer", confidence=None, kelly_fraction=None)
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.api.routes.trade_desk._strategy_health_for", new=AsyncMock(return_value=None)), \
         patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(None)), \
         patch.object(td.ibkr_coordinator, "submit",
                      new=AsyncMock(side_effect=asyncio.TimeoutError("timed out"))), \
         patch("app.services.trade_recorder.trade_recorder.record_fill",
               new=AsyncMock(return_value="trade-pending-2")) as record_mock:
        res = await _execute_signal(sig, approved_by="user")

    assert res["result"] == "pending_confirmation"
    assert res["asset_type"] == "equity"
    record_mock.assert_awaited_once()
    assert record_mock.await_args.kwargs["status"] == "pending"
    assert record_mock.await_args.kwargs["dispatch_id"] == "e1"
    assert record_mock.await_args.kwargs["option_type"] == "equity_long"


@pytest.mark.asyncio
async def test_duplicate_open_trade_skipped():
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(existing=("trade-x",))), \
         patch("app.broker.broker_factory.get_broker", return_value=MagicMock()):
        res = await _execute_signal(_options_signal(), approved_by="manual")
    assert res["result"] == "skipped" and "already_open" in res["reason"]


@pytest.mark.asyncio
async def test_duplicate_guard_allows_other_asset_class_same_underlying():
    """Open SPY equity must not block a new SPY options signal (and vice versa)."""
    equity_open = MagicMock()
    equity_open.id = "eq-1"
    equity_open.underlying = "SPY"
    equity_open.spread_type = "equity_long"
    equity_open.strategy = "equity"
    equity_open.status = "open"

    broker = MagicMock()
    broker.place_order = AsyncMock(return_value=MagicMock(order_id="ORD-opt", status="submitted"))
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.api.routes.trade_desk._strategy_health_for", new=AsyncMock(return_value=None)), \
         patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(existing=[equity_open])), \
         patch("app.services.trade_recorder.trade_recorder.record_fill",
               new=AsyncMock(return_value="trade-opt")):
        res = await _execute_signal(_options_signal(), approved_by="manual")
    assert res["result"] == "submitted"
    broker.place_order.assert_awaited_once()


# ── Stage 1c: Equity Desk composer confidence-gate carve-out ──────────────────────
def _equity_signal(**overrides):
    sig = {
        "id": "e1", "ticker": "AAPL", "action": "BUY", "asset_type": "equity",
        "trade_plan": {"shares": 10, "entry_price": 150.0, "stop_price": 147.0,
                        "target_price": 156.0},
        "source": "scan_engine", "confidence": 0.1, "kelly_fraction": 0.1,
    }
    sig.update(overrides)
    return sig


@pytest.mark.asyncio
async def test_equity_desk_composer_order_bypasses_confidence_gate():
    """Regression: a human-composed Equity Desk order (no AI signal behind
    it) must not be silently blocked by the AI-signal confidence gate —
    every mode's min_confidence exceeds a fabricated 0.5, so this order
    would previously be blocked unconditionally."""
    broker = MagicMock()
    broker.get_latest_quote = AsyncMock(return_value=MagicMock(ask_price=150.5, bid_price=150.0))
    broker.place_equity_order = AsyncMock(return_value=MagicMock(order_id="ORD-1", status="filled"))
    sig = _equity_signal(source="equity_desk_composer", confidence=None, kelly_fraction=None)
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch("app.api.routes.trade_desk._strategy_health_for", new=AsyncMock(return_value=None)), \
         patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_dup_session(None)), \
         patch("app.services.trade_recorder.trade_recorder.record_fill",
               new=AsyncMock(return_value="trade-e1")):
        res = await _execute_signal(sig, approved_by="user")
    assert res["result"] == "submitted"
    broker.place_equity_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_signal_low_confidence_still_blocked_when_approved_by_user():
    """The carve-out must be scoped to equity_desk_composer only — a real
    AI scan signal with genuinely low confidence, approved by a human,
    must still be caught by the frequency controller."""
    sig = _equity_signal(source="scan_engine", confidence=0.1)
    with patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=_clean())), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False):
        res = await _execute_signal(sig, approved_by="user")
    assert res["result"] == "blocked"
    assert "below_min_confidence" in res["reason"]
