import inspect
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.api.routes import trade_desk
from app.api.routes.trade_desk import (
    ManualTradeRequest,
    OrderDispatchOutcome,
    OrderIntent,
    OrderRiskContext,
    RiskStateUnavailable,
)
from app.services.execution_mode import ExecutionMode, execution_mode_manager
from app.services.guardrails import PortfolioState
from app.services.risk_manager import PortfolioRiskState, ProposedTrade
from app.services.unified_risk import RiskDecision


def _signal(asset_type: str = "equity") -> dict:
    if asset_type == "options":
        return {
            "id": "sig-opt",
            "ticker": "SPY",
            "asset_type": "options",
            "strategy": "bull_put_spread",
            "action": "SELL_SPREAD",
            "spread": {
                "option_type": "put",
                "short_strike": 450,
                "long_strike": 440,
                "expiration": "2026-07-17",
                "net_credit": 1.25,
                "max_loss": 875,
            },
        }
    return {
        "id": "sig-eq",
        "ticker": "SPY",
        "asset_type": "equity",
        "action": "BUY",
        "trade_plan": {"shares": 10, "entry_price": 500.0},
    }


def _context() -> OrderRiskContext:
    return OrderRiskContext(
        portfolio_state=PortfolioState(
            current_value=25_000,
            starting_capital=25_000,
            daily_pnl=0,
            weekly_pnl=0,
            monthly_pnl=0,
            consecutive_losses=0,
            trades_today=0,
        ),
        portfolio_risk_state=PortfolioRiskState(
            net_delta=0,
            net_vega=0,
            net_theta=0,
            open_position_count=0,
            portfolio_value=25_000,
            positions_by_underlying={},
            positions_by_sector={},
        ),
        proposed_trade=ProposedTrade(
            strategy="equity",
            underlying="SPY",
            sector="unknown",
            delta=0,
            vega=0,
            max_loss_dollars=500,
        ),
        size_multiplier=1.0,
    )


@pytest.fixture(autouse=True)
def clear_execution_state():
    trade_desk._execution_log.clear()
    trade_desk._pending_approvals.clear()
    execution_mode_manager.set_mode(ExecutionMode.MANUAL)
    yield
    trade_desk._execution_log.clear()
    trade_desk._pending_approvals.clear()
    execution_mode_manager.set_mode(ExecutionMode.MANUAL)


@pytest.fixture
def passing_stages(monkeypatch):
    monkeypatch.setattr(trade_desk, "_check_kill_switch_stage", AsyncMock())
    monkeypatch.setattr(trade_desk, "_load_order_context_stage", AsyncMock(return_value=_context()))
    monkeypatch.setattr(
        trade_desk,
        "_run_unified_risk_stage",
        lambda intent, context: RiskDecision(allowed=True, reason=None),
    )
    monkeypatch.setattr(trade_desk, "_size_order_stage", lambda intent, context: 1)
    monkeypatch.setattr(
        trade_desk,
        "_dispatch_order_stage",
        AsyncMock(return_value=OrderDispatchOutcome(
            status="filled",
            order_id="order-1",
            fill_price=Decimal("1.25"),
        )),
    )
    monkeypatch.setattr(trade_desk, "_record_filled_order_stage", AsyncMock())


@pytest.mark.asyncio
async def test_autopilot_order_with_risk_breach_is_rejected(monkeypatch, passing_stages):
    dispatch = AsyncMock()
    monkeypatch.setattr(trade_desk, "_dispatch_order_stage", dispatch)
    monkeypatch.setattr(
        trade_desk,
        "_run_unified_risk_stage",
        lambda intent, context: RiskDecision(
            allowed=False,
            reason="daily loss breached",
            flags=["daily_loss_limit"],
        ),
    )
    execution_mode_manager.set_mode(ExecutionMode.AUTOPILOT)

    await trade_desk.handle_signal(_signal())

    dispatch.assert_not_called()
    assert trade_desk._execution_log[0]["result"] == "blocked"
    assert trade_desk._execution_log[0]["reason"] == "risk_block"


@pytest.mark.asyncio
async def test_manual_order_with_risk_breach_is_rejected(monkeypatch, passing_stages):
    dispatch = AsyncMock()
    monkeypatch.setattr(trade_desk, "_dispatch_order_stage", dispatch)
    monkeypatch.setattr(
        trade_desk,
        "_run_unified_risk_stage",
        lambda intent, context: RiskDecision(allowed=False, reason="blocked"),
    )

    result = await trade_desk.manual_trade(
        ManualTradeRequest(ticker="SPY", action="BUY", shares=5, limit_price=500)
    )

    dispatch.assert_not_called()
    assert result["result"] == "blocked"
    assert result["reason"] == "risk_block"


@pytest.mark.asyncio
async def test_copilot_approved_order_with_risk_breach_is_rejected(monkeypatch, passing_stages):
    dispatch = AsyncMock()
    monkeypatch.setattr(trade_desk, "_dispatch_order_stage", dispatch)
    monkeypatch.setattr(
        trade_desk,
        "_run_unified_risk_stage",
        lambda intent, context: RiskDecision(allowed=False, reason="blocked"),
    )
    trade_desk._pending_approvals["sig-eq"] = _signal()

    result = await trade_desk.approve_signal("sig-eq")

    dispatch.assert_not_called()
    assert result["result"] == "blocked"
    assert result["reason"] == "risk_block"


@pytest.mark.asyncio
async def test_guardrail_db_failure_blocks_order(monkeypatch, passing_stages):
    dispatch = AsyncMock()
    monkeypatch.setattr(trade_desk, "_dispatch_order_stage", dispatch)
    monkeypatch.setattr(
        trade_desk,
        "_load_order_context_stage",
        AsyncMock(side_effect=RiskStateUnavailable("missing column realized_pnl")),
    )

    result = await trade_desk._execute_signal(_signal(), approved_by="autopilot")

    dispatch.assert_not_called()
    assert result["result"] == "blocked"
    assert result["reason"] == "risk_state_unavailable"


@pytest.mark.asyncio
async def test_zero_size_skips_without_dispatch(monkeypatch, passing_stages):
    dispatch = AsyncMock()
    monkeypatch.setattr(trade_desk, "_dispatch_order_stage", dispatch)
    monkeypatch.setattr(trade_desk, "_size_order_stage", lambda intent, context: 0)

    result = await trade_desk._execute_signal(_signal(), approved_by="autopilot")

    dispatch.assert_not_called()
    assert result["result"] == "skipped"
    assert result["reason"] == "zero_size"


@pytest.mark.asyncio
async def test_clean_order_calls_stages_in_order(monkeypatch):
    calls: list[str] = []

    async def check(intent: OrderIntent):
        if "kill_switch" not in calls:
            calls.append("kill_switch")

    async def load(intent: OrderIntent):
        return _context()

    def risk(intent: OrderIntent, context: OrderRiskContext):
        calls.append("unified_risk")
        return RiskDecision(allowed=True, reason=None)

    def size(intent: OrderIntent, context: OrderRiskContext):
        calls.append("sizing")
        return 1

    async def dispatch(intent: OrderIntent, quantity: int):
        calls.append("dispatcher")
        return OrderDispatchOutcome(status="filled", order_id="order-1", fill_price=Decimal("1.25"))

    async def record(intent: OrderIntent, quantity: int, outcome: OrderDispatchOutcome):
        calls.append("recording")

    monkeypatch.setattr(trade_desk, "_check_kill_switch_stage", check)
    monkeypatch.setattr(trade_desk, "_load_order_context_stage", load)
    monkeypatch.setattr(trade_desk, "_run_unified_risk_stage", risk)
    monkeypatch.setattr(trade_desk, "_size_order_stage", size)
    monkeypatch.setattr(trade_desk, "_dispatch_order_stage", dispatch)
    monkeypatch.setattr(trade_desk, "_record_filled_order_stage", record)

    result = await trade_desk._execute_signal(_signal(), approved_by="autopilot")

    assert result["result"] == "filled"
    assert calls == ["kill_switch", "unified_risk", "sizing", "dispatcher", "recording"]


def test_handle_signal_has_no_second_guardrail_path():
    source = inspect.getsource(trade_desk.handle_signal)
    assert "GuardrailEngine" not in source
    assert "PortfolioState" not in source
    assert "Trade.pnl" not in source
