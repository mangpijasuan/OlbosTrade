"""
Batch-1 acceptance tests — single fail-closed order pipeline (order_gate).

Covers audit issues 1, 9, 14, 17 plus the two extra findings:
  - every entry point funnels through the gate (signal/autopilot, copilot, manual)
  - risk breach => rejected, dispatcher never reached
  - unreadable risk state => fail closed (no order)
  - zero size => no order
  - clean order runs all five stages IN ORDER
  - no second guardrail path remains in handle_signal

These patch the gate's seams so no real broker/DB is needed. Run with:
    pytest backend/tests/test_order_gate.py
"""

from __future__ import annotations

import pathlib
import types

import pytest

from app.services import order_gate as gate_mod
from app.services.order_gate import OrderGate
from app.services.unified_risk import RiskDecision


# ── helpers ──────────────────────────────────────────────────────────────────
def _options_signal():
    return {
        "id": "sig-1", "ticker": "SPY", "asset_type": "options",
        "strategy": "bull_put_spread",
        "spread": {"short_strike": 500, "long_strike": 495, "net_credit": 1.0,
                   "option_type": "put", "expiration": "2026-07-17"},
    }


class _FakeState:
    current_value = 25000.0


def _patch_common(monkeypatch, gate, *, allowed=True, size=1, open_trade=False):
    """Patch all seams to a clean baseline; individual tests override pieces."""
    monkeypatch.setattr(gate, "_kill_switch_active", lambda: False)
    async def _no_open(t): return open_trade
    monkeypatch.setattr(gate, "_has_open_trade", _no_open)
    async def _pstate(): return _FakeState()
    async def _prisk(v): return object()
    monkeypatch.setattr(gate, "_read_portfolio_state", _pstate)
    monkeypatch.setattr(gate, "_read_portfolio_risk_state", _prisk)
    monkeypatch.setattr(gate._risk_engine, "check",
                        lambda **k: RiskDecision(allowed=allowed, reason=None if allowed else "breach", flags=[]))
    # sizing
    from app.services.risk_manager import RiskManager
    monkeypatch.setattr(RiskManager, "calculate_position_size",
                        lambda self, *a, **k: size)


class _FakeDispatch:
    def __init__(self, broker, **k): pass
    async def validate_and_dispatch(self, strategy, dry_run=False):
        from app.services.execution_dispatcher import DispatchResult, DispatchStatus
        return DispatchResult(order_id="ord-1", status=DispatchStatus.FILLED,
                              strategy=strategy.strategy_name, underlying=strategy.underlying,
                              fills=[], net_fill_price=1.0)


# ── tests ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_signal_breach_rejected_no_dispatch(monkeypatch):
    gate = OrderGate()
    _patch_common(monkeypatch, gate, allowed=False)
    spy = {"called": False}
    monkeypatch.setattr(gate, "_build_strategy",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dispatch reached")))
    res = await gate.submit(_options_signal(), approved_by="autopilot")
    assert res["result"] == "blocked"
    assert res["reason"] == "breach"


@pytest.mark.asyncio
async def test_manual_breach_rejected(monkeypatch):
    gate = OrderGate()
    _patch_common(monkeypatch, gate, allowed=False)
    sig = {"id": "m1", "ticker": "AAPL", "asset_type": "equity", "action": "BUY",
           "trade_plan": {"shares": 10, "entry_price": 200, "stop_price": 190}}
    res = await gate.submit(sig, approved_by="manual")
    assert res["result"] == "blocked"


@pytest.mark.asyncio
async def test_copilot_breach_rejected(monkeypatch):
    gate = OrderGate()
    _patch_common(monkeypatch, gate, allowed=False)
    res = await gate.submit(_options_signal(), approved_by="user")
    assert res["result"] == "blocked"


@pytest.mark.asyncio
async def test_guardrail_read_raises_fails_closed(monkeypatch):
    gate = OrderGate()
    _patch_common(monkeypatch, gate)
    async def _boom(): raise RuntimeError("db down")
    monkeypatch.setattr(gate, "_read_portfolio_state", _boom)
    monkeypatch.setattr(gate, "_build_strategy",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dispatch reached")))
    res = await gate.submit(_options_signal())
    assert res["result"] == "blocked"
    assert res["reason"] == "risk_state_unavailable"


@pytest.mark.asyncio
async def test_zero_size_no_order(monkeypatch):
    gate = OrderGate()
    _patch_common(monkeypatch, gate, allowed=True, size=0)
    monkeypatch.setattr(gate, "_build_strategy",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dispatch reached")))
    res = await gate.submit(_options_signal())
    assert res["result"] == "skipped"
    assert res["reason"] == "zero_size"


@pytest.mark.asyncio
async def test_clean_order_runs_five_stages_in_order(monkeypatch):
    gate = OrderGate()
    order: list[str] = []

    monkeypatch.setattr(gate, "_kill_switch_active", lambda: (order.append("KS"), False)[1]
                        if not order or order[-1] != "KS" else False)
    async def _no_open(t): return False
    monkeypatch.setattr(gate, "_has_open_trade", _no_open)

    async def _pstate(): order.append("UR"); return _FakeState()
    async def _prisk(v): return object()
    monkeypatch.setattr(gate, "_read_portfolio_state", _pstate)
    monkeypatch.setattr(gate, "_read_portfolio_risk_state", _prisk)
    monkeypatch.setattr(gate._risk_engine, "check",
                        lambda **k: RiskDecision(allowed=True, reason=None, flags=[]))

    from app.services.risk_manager import RiskManager
    def _size(self, *a, **k): order.append("SZ"); return 1
    monkeypatch.setattr(RiskManager, "calculate_position_size", _size)

    async def _build(signal, broker, qty):
        order.append("ED-build")
        return types.SimpleNamespace(strategy_name="bull_put_spread", underlying="SPY")
    monkeypatch.setattr(gate, "_build_strategy", _build)
    monkeypatch.setattr("app.services.execution_dispatcher.ExecutionDispatcher", _FakeDispatch)
    monkeypatch.setattr("app.broker.broker_factory.get_broker", lambda: object())

    async def _rec(*a, **k): order.append("REC")
    monkeypatch.setattr(gate, "_record_options", _rec)

    res = await gate.submit(_options_signal())
    assert res["result"] == "submitted", res
    # KS first, then UR → SZ → ED → REC
    assert order[0] == "KS"
    assert order.index("UR") < order.index("SZ") < order.index("ED-build") < order.index("REC")


def test_no_second_guardrail_path_in_handle_signal():
    """handle_signal must not re-implement guardrails or use the broken columns."""
    src = pathlib.Path(__file__).resolve().parents[1] / "app/api/routes/trade_desk.py"
    text = src.read_text()
    # the duplicated inline guardrail block and the non-existent columns are gone
    assert "realized_pnl" not in text
    assert "closed_at" not in text
    assert "GuardrailEngine()" not in text
    # _execute_signal funnels to the single gate
    assert "order_gate.submit" in text
