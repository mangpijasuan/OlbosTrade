"""
Broker execution-safety tests (Batch 2) for IBKRClient.place_order and the
kill-switch flatten path.

These use a lightweight fake `ib` object so we can assert exactly what order
objects / combo contracts get constructed, without a live IB Gateway. ib_insync's
real LimitOrder / MarketOrder / ComboLeg / Contract classes are used so the
assertions reflect real attribute names.

Run with: pytest tests/test_ibkr_execution.py -v
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker.broker_interface import SpreadLeg, SpreadOrder
from app.broker.ibkr_client import IBKRClient


# ── Fakes ──────────────────────────────────────────────────────────────────────

class _OrderStatus:
    def __init__(self, status="Submitted", filled=0, avg=0.0):
        self.status = status
        self.filled = filled
        self.avgFillPrice = avg


class _Event:
    """Stand-in for ib_insync Event — ignores handler registration."""
    def __iadd__(self, _fn):
        return self


class _Trade:
    def __init__(self, order, order_status):
        self.order = order
        self.orderStatus = order_status
        self.statusEvent = _Event()
        self.fillEvent = _Event()


class FakeIB:
    """Minimal ib_insync.IB replacement for place_order tests."""
    def __init__(self, status_script):
        # status_script: list of _OrderStatus, one returned per placeOrder call
        self._script = list(status_script)
        self.placed = []      # list of (contract, order)
        self.cancelled = []
        self._conid = 1000

    def isConnected(self):
        return True

    async def qualifyContractsAsync(self, opt):
        self._conid += 1
        opt.conId = self._conid
        return [opt]

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        st = self._script.pop(0) if self._script else _OrderStatus()
        order.orderId = len(self.placed)
        return _Trade(order, st)

    def cancelOrder(self, order):
        self.cancelled.append(order)


def _make_client(status_script):
    c = IBKRClient()
    c._connected = True
    c.ib = FakeIB(status_script)
    return c


def _credit_spread(limit=Decimal("1.50"), order_type="LMT", q_short=1, q_long=1):
    return SpreadOrder(
        strategy="bull_put_spread",
        underlying="SPY",
        legs=[
            SpreadLeg(symbol="SPY", strike=Decimal("450"), expiration=date(2025, 1, 17),
                      option_type="put", action="SELL", quantity=q_short),
            SpreadLeg(symbol="SPY", strike=Decimal("445"), expiration=date(2025, 1, 17),
                      option_type="put", action="BUY", quantity=q_long),
        ],
        limit_price=limit,
        order_type=order_type,
        time_in_force="DAY",
    )


# Patch out the real 1-2s sleeps so tests run instantly.
@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("app.broker.ibkr_client.asyncio.sleep", new_callable=AsyncMock):
        yield


# ── Combo sizing (task 4) ───────────────────────────────────────────────────────

class TestComboSizing:
    def test_equal_quantities_ratio_one(self):
        legs = _credit_spread(q_short=5, q_long=5).legs
        qty, ratios = IBKRClient._combo_sizing(legs)
        assert qty == 5
        assert ratios == [1, 1]

    def test_ratio_spread_normalised(self):
        legs = _credit_spread(q_short=5, q_long=10).legs
        qty, ratios = IBKRClient._combo_sizing(legs)
        assert qty == 5
        assert ratios == [1, 2]

    def test_single_contract(self):
        legs = _credit_spread(q_short=1, q_long=1).legs
        qty, ratios = IBKRClient._combo_sizing(legs)
        assert qty == 1
        assert ratios == [1, 1]


# ── MKT vs LMT + single combo BAG (tasks 1, 3, 4) ────────────────────────────────

class TestPlaceOrderConstruction:
    @pytest.mark.asyncio
    async def test_multileg_sent_as_single_bag_combo(self):
        client = _make_client([_OrderStatus("Filled", 1, 1.50)])
        await client.place_order(_credit_spread())

        # Exactly ONE order placed — never legged out into separate orders.
        assert len(client.ib.placed) == 1
        contract, order = client.ib.placed[0]
        assert contract.secType == "BAG"
        assert len(contract.comboLegs) == 2

    @pytest.mark.asyncio
    async def test_lmt_credit_uses_negative_net_price(self):
        client = _make_client([_OrderStatus("Filled", 1, 1.50)])
        await client.place_order(_credit_spread(limit=Decimal("1.50")))

        _, order = client.ib.placed[0]
        assert order.orderType == "LMT"
        assert order.action == "BUY"
        # Credit of 1.50 → BUY combo at a net price of -1.50 (we receive credit).
        assert order.lmtPrice == -1.50
        assert order.totalQuantity == 1

    @pytest.mark.asyncio
    async def test_mkt_builds_market_order(self):
        client = _make_client([_OrderStatus("Filled", 1, 1.50)])
        await client.place_order(_credit_spread(order_type="MKT"))

        _, order = client.ib.placed[0]
        assert order.orderType == "MKT"
        # Market order must not carry a real limit price — ib_insync leaves it as
        # the UNSET sentinel (a huge double), never a meaningful number.
        assert order.lmtPrice >= 1e307

    @pytest.mark.asyncio
    async def test_combo_ratio_sizing_applied(self):
        client = _make_client([_OrderStatus("Filled", 5, 1.50)])
        await client.place_order(_credit_spread(q_short=5, q_long=10))

        contract, order = client.ib.placed[0]
        assert order.totalQuantity == 5
        assert [leg.ratio for leg in contract.comboLegs] == [1, 2]

    @pytest.mark.asyncio
    async def test_single_leg_uses_plain_option_not_bag(self):
        client = _make_client([_OrderStatus("Filled", 1, 2.00)])
        single = SpreadOrder(
            strategy="kill_switch_flatten", underlying="SPY",
            legs=[SpreadLeg(symbol="SPY", strike=Decimal("450"),
                            expiration=date(2025, 1, 17), option_type="put",
                            action="BUY", quantity=1)],
            limit_price=Decimal("2.00"), order_type="LMT", time_in_force="DAY",
        )
        await client.place_order(single)

        contract, order = client.ib.placed[0]
        assert contract.secType == "OPT"          # plain option, not a BAG
        assert order.action == "BUY"              # uses the leg's own action
        assert order.lmtPrice == 2.00             # single-leg price used as-is


# ── Partial fills (task 5) ───────────────────────────────────────────────────────

class TestPartialFills:
    @pytest.mark.asyncio
    async def test_full_fill_reports_filled(self):
        client = _make_client([_OrderStatus("Filled", 5, 1.50)])
        result = await client.place_order(_credit_spread(q_short=5, q_long=5))
        assert result.status == "filled"
        assert result.filled_quantity == 5
        assert result.remaining_quantity == 0

    @pytest.mark.asyncio
    async def test_partial_fill_reported_not_filled(self):
        # Order shows 3 of 5 filled but still "Submitted" → must be PARTIAL,
        # never reported as a clean fill.
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0):
            client = _make_client([_OrderStatus("Submitted", 3, 1.48)])
            result = await client.place_order(_credit_spread(q_short=5, q_long=5))
        assert result.status == "partial"
        assert result.filled_quantity == 3
        assert result.remaining_quantity == 2
        # The residual must be cancelled so it does not keep working.
        assert len(client.ib.cancelled) == 1

    @pytest.mark.asyncio
    async def test_cancelled_with_fill_is_partial(self):
        client = _make_client([_OrderStatus("Cancelled", 2, 1.45)])
        result = await client.place_order(_credit_spread(q_short=5, q_long=5))
        assert result.status == "partial"
        assert result.filled_quantity == 2

    @pytest.mark.asyncio
    async def test_rejected_no_fill(self):
        client = _make_client([_OrderStatus("Rejected", 0, 0.0)])
        result = await client.place_order(_credit_spread())
        assert result.status == "rejected"
        assert result.filled_quantity == 0

    @pytest.mark.asyncio
    async def test_lmt_timeout_retries_then_cancels(self):
        # Every attempt times out with no fill → should retry (LMT) then cancel.
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0), \
             patch("app.broker.ibkr_client._max_retries", return_value=2):
            client = _make_client([_OrderStatus("Submitted", 0, 0.0)] * 3)
            result = await client.place_order(_credit_spread())
        assert result.status == "cancelled"
        assert len(client.ib.placed) == 3       # initial + 2 retries
        assert len(client.ib.cancelled) == 3

    @pytest.mark.asyncio
    async def test_mkt_no_fill_stays_working(self):
        # A market flatten that has not filled must be left working, not cancelled.
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0):
            client = _make_client([_OrderStatus("Submitted", 0, 0.0)])
            result = await client.place_order(_credit_spread(order_type="MKT"))
        assert result.status == "submitted"
        assert len(client.ib.cancelled) == 0
        assert len(client.ib.placed) == 1       # MKT does not retry


# ── Equity bracket orders: parent-ack race (Error 135) ──────────────────────────
#
# Regression coverage for a live production bug: the take-profit/stop-loss
# children reference the parent order via parentId, but nothing waited for
# IBKR to actually register the parent before the children were submitted --
# so the Gateway would reject both children with "Error 135: Can't find order
# with id" a few hundred ms later, leaving the entry order dangling with no
# protective exits attached. Confirmed twice in production logs on the same day
# (same failure signature both times: children cancelled ~150-300ms after
# PendingSubmit, parent timed out at 60s unfilled).
#
# Unlike FakeIB above (which reassigns orderId on every placeOrder call --
# harmless for the single-order combo path it was built for, but it would
# clobber the explicit parentId linkage this test needs to verify), this fake
# preserves whatever orderId the caller set beforehand, matching real
# ib_insync/IBKR semantics for pre-assigned order IDs.

class _EquityFakeIB:
    def __init__(self, parent_status: str):
        self.placed: list = []
        self._parent_status = parent_status
        self.client = MagicMock()
        self.client.getReqId.side_effect = iter(range(100, 200))

    def isConnected(self):
        return True

    async def qualifyContractsAsync(self, contract):
        contract.conId = 999
        return [contract]

    def placeOrder(self, contract, order):
        # Preserve the caller-assigned orderId (real ib_insync does the same)
        # instead of reassigning it, so parentId linkage stays verifiable.
        is_parent = not getattr(order, "parentId", 0)
        status = self._parent_status if is_parent else "Submitted"
        trade = _Trade(order, _OrderStatus(status, 0, 0.0))
        self.placed.append(trade)
        return trade


def _make_equity_client(parent_status: str) -> IBKRClient:
    c = IBKRClient()
    c._connected = True
    c.ib = _EquityFakeIB(parent_status)
    return c


class TestEquityBracketAck:
    @pytest.mark.asyncio
    async def test_children_wait_for_parent_ack_before_sending(self):
        # Parent acknowledges immediately (non-empty status) -- children should
        # be sent right away, correctly linked via parentId.
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0):
            client = _make_equity_client(parent_status="PreSubmitted")
            await client.place_equity_order(
                "NVDA", 10, "BUY", order_type="market",
                stop=190.0, take_profit=210.0,
            )
        placed = client.ib.placed
        assert len(placed) == 3   # parent + take-profit + stop-loss
        parent = placed[0].order
        tp, sl = placed[1].order, placed[2].order
        assert parent.parentId in (0, None)
        assert tp.parentId == parent.orderId
        assert sl.parentId == parent.orderId

    @pytest.mark.asyncio
    async def test_unacknowledged_parent_times_out_then_still_sends_children(self):
        # Parent never acknowledges (status stays empty) -- must not hang
        # forever; bounded by BRACKET_ACK_TIMEOUT_SECONDS, then proceeds anyway.
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0), \
             patch("app.broker.ibkr_client.BRACKET_ACK_TIMEOUT_SECONDS", 0.05):
            client = _make_equity_client(parent_status="")
            await client.place_equity_order(
                "NVDA", 10, "BUY", order_type="market",
                stop=190.0, take_profit=210.0,
            )
        # Children still get sent (matching current behaviour: log + proceed
        # rather than silently dropping the bracket's protective exits).
        assert len(client.ib.placed) == 3


# ── Equity LMT retry-and-reprice (mirrors options' place_order behavior) ────────
#
# Regression coverage for a real production bug: equity LMT orders that timed
# out unfilled were given up on after a single attempt and left "working" at
# IBKR indefinitely, with only a DB-side 30-minute grace period marking the
# trade cancelled (never telling the broker to cancel the resting order).
# Confirmed in production: AMZN/NVDA/QQQ timed out on effectively every
# attempt for days (IBKR's free delayed 15-min data feed means the "live"
# quote used to set the limit is itself already stale, and faster-moving
# names drift past a stale limit within that window). place_equity_order now
# retries like place_order already does: cancel, reprice more aggressively,
# resubmit, up to _max_retries() times.

class TestEquityLimitRetry:
    @pytest.mark.asyncio
    async def test_lmt_timeout_retries_then_cancels(self):
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0), \
             patch("app.broker.ibkr_client._max_retries", return_value=2):
            client = _make_client([_OrderStatus("Submitted", 0, 0.0)] * 3)
            result = await client.place_equity_order(
                "AMZN", 74, "BUY", order_type="limit", limit_price=268.00,
            )
        assert result.status == "cancelled"
        assert len(client.ib.placed) == 3        # initial + 2 retries
        assert len(client.ib.cancelled) == 3

    @pytest.mark.asyncio
    async def test_buy_reprices_upward_on_each_retry(self):
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0), \
             patch("app.broker.ibkr_client._max_retries", return_value=2):
            client = _make_client([_OrderStatus("Submitted", 0, 0.0)] * 3)
            await client.place_equity_order(
                "AMZN", 74, "BUY", order_type="limit", limit_price=268.00,
            )
        prices = [order.lmtPrice for _, order in client.ib.placed]
        # BUY retries get more aggressive (higher) each attempt — more likely
        # to be marketable against a price that has drifted upward.
        assert prices[0] == 268.00
        assert prices[1] > prices[0]
        assert prices[2] > prices[1]

    @pytest.mark.asyncio
    async def test_sell_reprices_downward_on_each_retry(self):
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0), \
             patch("app.broker.ibkr_client._max_retries", return_value=2):
            client = _make_client([_OrderStatus("Submitted", 0, 0.0)] * 3)
            await client.place_equity_order(
                "AMZN", 74, "SELL", order_type="limit", limit_price=268.00,
            )
        prices = [order.lmtPrice for _, order in client.ib.placed]
        assert prices[0] == 268.00
        assert prices[1] < prices[0]
        assert prices[2] < prices[1]

    @pytest.mark.asyncio
    async def test_mkt_no_fill_stays_working_not_cancelled(self):
        with patch("app.broker.ibkr_client._fill_timeout", return_value=0):
            client = _make_client([_OrderStatus("Submitted", 0, 0.0)])
            result = await client.place_equity_order(
                "AMZN", 74, "BUY", order_type="market",
            )
        assert result.status == "submitted"
        assert len(client.ib.cancelled) == 0
        assert len(client.ib.placed) == 1        # MKT does not retry

    @pytest.mark.asyncio
    async def test_rejected_no_fill_not_retried(self):
        client = _make_client([_OrderStatus("Rejected", 0, 0.0)])
        result = await client.place_equity_order(
            "AMZN", 74, "BUY", order_type="limit", limit_price=268.00,
        )
        assert result.status == "rejected"
        assert len(client.ib.placed) == 1

    @pytest.mark.asyncio
    async def test_partial_fill_reported_as_filled_not_cancelled(self):
        # Terminated with a real, non-zero fill — must report status="filled"
        # (EquityOrderResult has no "partial" status) rather than "cancelled",
        # which would wrongly suggest nothing happened at the broker.
        client = _make_client([_OrderStatus("Cancelled", 40, 268.50)])
        result = await client.place_equity_order(
            "AMZN", 74, "BUY", order_type="limit", limit_price=268.00,
        )
        assert result.status == "filled"
        assert result.fill_price == Decimal("268.5")
