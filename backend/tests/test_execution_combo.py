"""
Batch-2 tests — broker/combo/MKT execution correctness.

Covers:
  - real orders submit ONE native combo (atomic), not leg-by-leg (naked-exposure fix)
  - a combo that doesn't fill returns REJECTED with NO flatten (all-or-none)
  - duplicate in-flight dispatch is refused (idempotency)
  - to_spread_order limit price is per-spread-per-share (correct for qty>1)
  - to_spread_order passes order_type through (MKT honored downstream)

Pure-unit; no live broker. Run: pytest backend/tests/test_execution_combo.py
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.broker.broker_interface import OrderResult
from app.broker.contract import EnrichedContract
from app.services.execution_dispatcher import ExecutionDispatcher, DispatchStatus
from app.services.multi_leg_strategy import MultiLegStrategy, StrategyLeg, LegAction


def _contract(strike: float, bid: float, ask: float) -> EnrichedContract:
    return EnrichedContract(
        underlying_ticker="SPY", strike_price=strike,
        expiration_date=date(2026, 7, 17), option_type="put",
        bid=bid, ask=ask, last=(bid + ask) / 2, volume=5000, open_interest=10000,
    )


def _spread(qty: int = 1) -> MultiLegStrategy:
    # tight spreads so the liquidity guard passes
    return MultiLegStrategy(
        strategy_name="bull_put_spread", underlying="SPY",
        legs=[
            StrategyLeg(contract=_contract(500, 1.20, 1.24), action=LegAction.SELL, quantity=qty),
            StrategyLeg(contract=_contract(495, 0.58, 0.62), action=LegAction.BUY, quantity=qty),
        ],
    )


class _FakeBroker:
    def __init__(self, status="filled", fill=1.0):
        self.calls = 0
        self._status, self._fill = status, fill
    async def place_order(self, order):
        self.calls += 1
        return OrderResult(order_id="ord-9", status=self._status,
                           fill_price=self._fill, filled_at=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_real_order_uses_single_combo(monkeypatch):
    broker = _FakeBroker(status="filled", fill=0.60)
    disp = ExecutionDispatcher(broker, max_spread_pct=15.0)
    # ensure the per-leg path is NOT used for real orders
    async def _boom(*a, **k): raise AssertionError("per-leg submission used for real order")
    monkeypatch.setattr(disp, "_submit_leg_with_timeout", _boom)

    res = await disp.validate_and_dispatch(_spread(), dry_run=False)
    assert res.status == DispatchStatus.FILLED
    assert broker.calls == 1            # exactly one combo order
    assert res.net_fill_price == 0.60


@pytest.mark.asyncio
async def test_combo_not_filled_no_flatten():
    broker = _FakeBroker(status="cancelled", fill=None)
    disp = ExecutionDispatcher(broker, max_spread_pct=15.0)
    res = await disp.validate_and_dispatch(_spread(), dry_run=False)
    assert res.status == DispatchStatus.REJECTED
    assert res.flatten is None          # all-or-none — nothing to flatten


@pytest.mark.asyncio
async def test_duplicate_inflight_refused():
    broker = _FakeBroker()
    disp = ExecutionDispatcher(broker, max_spread_pct=15.0)
    strat = _spread()
    disp._inflight.add(strat.order_id)   # simulate one already dispatching
    res = await disp.validate_and_dispatch(strat, dry_run=False)
    assert res.status == DispatchStatus.REJECTED
    assert res.error == "duplicate_inflight"
    assert broker.calls == 0


def test_limit_price_per_spread_for_qty_gt_1():
    one = _spread(qty=1).to_spread_order()
    two = _spread(qty=2).to_spread_order()
    # per-spread limit must be identical regardless of quantity (was 2x too big)
    assert float(one.limit_price) == pytest.approx(float(two.limit_price), abs=1e-6)
    # credit spread → positive net premium → positive limit
    assert float(one.limit_price) > 0


def test_order_type_passthrough():
    o = _spread().to_spread_order(order_type="MKT")
    assert o.order_type == "MKT"
