"""
Unit tests for the IBKR Client Portal Web API broker client.

A live Client Portal Gateway is not available in CI, so these drive the client
through an httpx MockTransport that records requests and returns canned JSON —
verifying endpoints, the combo ``conidex`` shape, the credit price sign, the
reply-confirmation handshake, bracket construction, and partial-fill handling.

Run with: pytest tests/test_ibkr_cp_client.py -v
"""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.broker.broker_interface import SpreadLeg, SpreadOrder
from app.broker.ibkr_cp_client import IBKRClientPortalClient, _combo_sizing


class FakeGateway:
    """Routes Client Portal requests to canned responses and records them."""

    def __init__(self, order_status="Filled", filled=1, avg=1.50, reply_first=False):
        self.requests: list[httpx.Request] = []
        self.order_bodies: list[dict] = []
        self.order_status = order_status
        self.filled = filled
        self.avg = avg
        self.reply_first = reply_first        # first /orders reply is a confirmation question
        self._order_posts = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        method = request.method

        def j(payload):
            return httpx.Response(200, json=payload)

        if path.endswith("/iserver/auth/status"):
            return j({"authenticated": True, "connected": True})
        if path.endswith("/tickle"):
            return j({"session": "abc"})
        if path.endswith("/iserver/accounts"):
            return j({"accounts": ["DU1234567"]})
        if path.endswith("/iserver/secdef/search"):
            return j([{"conid": 265598, "symbol": "SPY"}])
        if path.endswith("/iserver/secdef/info"):
            return j([{"conid": 700001, "maturityDate": "20250117"}])
        if path.endswith("/iserver/marketdata/snapshot"):
            return j([{"31": "450.10", "84": "449.90", "86": "450.30",
                       "88": "11", "85": "13"}])
        if path.endswith("/iserver/marketdata/history"):
            return j({"data": [{"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5,
                                "v": 1000, "t": 1700000000000}]})
        if "/portfolio/" in path and path.endswith("/summary"):
            return j({"netliquidation": {"amount": 25000.0},
                      "totalcashvalue": {"amount": 20000.0},
                      "buyingpower": {"amount": 40000.0}})
        if "/portfolio/" in path and "/positions/" in path:
            if path.endswith("/positions/0"):
                return j([
                    {"assetClass": "OPT", "conid": 700001, "position": -1,
                     "avgCost": 125.0, "contractDesc": "SPY 17JAN25 450 P",
                     "strike": "450", "expiry": "20250117", "putOrCall": "P",
                     "undSym": "SPY"},
                    {"assetClass": "STK", "conid": 265598, "position": 100,
                     "avgCost": 180.0, "ticker": "AAPL"},
                ])
            return j([])
        if path.endswith(f"/orders") and method == "POST":
            self._order_posts += 1
            try:
                self.order_bodies.append(json.loads(request.content))
            except Exception:
                self.order_bodies.append({})
            if self.reply_first and self._order_posts == 1:
                return j([{"id": "reply-1", "message": ["Confirm order?"]}])
            return j([{"order_id": "ORD-1", "order_status": "Submitted"}])
        if "/iserver/reply/" in path:
            return j([{"order_id": "ORD-1", "order_status": "Submitted"}])
        if "/iserver/account/order/status/" in path:
            return j({"order_status": self.order_status,
                      "filled_quantity": self.filled,
                      "average_price": self.avg})
        if path.endswith("/order/") or "/order/" in path and method == "DELETE":
            return j({"msg": "cancelled"})
        if path.endswith("/iserver/account/orders"):
            return j({"orders": []})
        return httpx.Response(200, json={})


def _make_client(gateway: FakeGateway) -> IBKRClientPortalClient:
    c = IBKRClientPortalClient()
    c._transport = httpx.MockTransport(gateway.handler)
    c._connected = True
    c._account_id = "DU1234567"
    c._fill_timeout = lambda: 5     # short; sleep is patched to no-op anyway
    return c


def _credit_spread(limit=Decimal("1.50"), order_type="LMT", q_short=1, q_long=1):
    return SpreadOrder(
        strategy="bull_put_spread", underlying="SPY",
        legs=[
            SpreadLeg(symbol="SPY", strike=Decimal("450"), expiration=date(2025, 1, 17),
                      option_type="put", action="SELL", quantity=q_short),
            SpreadLeg(symbol="SPY", strike=Decimal("445"), expiration=date(2025, 1, 17),
                      option_type="put", action="BUY", quantity=q_long),
        ],
        limit_price=limit, order_type=order_type, time_in_force="DAY",
    )


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("app.broker.ibkr_cp_client.asyncio.sleep", new_callable=AsyncMock):
        yield


# ── Combo sizing ────────────────────────────────────────────────────────────────

class TestComboSizing:
    def test_equal(self):
        assert _combo_sizing(_credit_spread(q_short=5, q_long=5).legs) == (5, [1, 1])

    def test_ratio(self):
        assert _combo_sizing(_credit_spread(q_short=5, q_long=10).legs) == (5, [1, 2])


# ── Session / account ───────────────────────────────────────────────────────────

class TestSession:
    @pytest.mark.asyncio
    async def test_connect_resolves_account(self):
        gw = FakeGateway()
        c = IBKRClientPortalClient()
        c._transport = httpx.MockTransport(gw.handler)
        c._account_id = None
        await c.connect()
        assert c._connected is True
        assert c.account_id == "DU1234567"

    @pytest.mark.asyncio
    async def test_connect_raises_when_unauthenticated(self):
        def handler(request):
            if request.url.path.endswith("/iserver/auth/status"):
                return httpx.Response(200, json={"authenticated": False})
            if request.url.path.endswith("/iserver/reauthenticate"):
                return httpx.Response(200, json={})
            return httpx.Response(200, json={})
        c = IBKRClientPortalClient()
        c._transport = httpx.MockTransport(handler)
        with pytest.raises(ConnectionError, match="not authenticated"):
            await c.connect()


# ── Market data / account / positions ────────────────────────────────────────────

class TestReads:
    @pytest.mark.asyncio
    async def test_latest_quote(self):
        c = _make_client(FakeGateway())
        q = await c.get_latest_quote("SPY")
        assert q.bid_price == Decimal("449.90")
        assert q.ask_price == Decimal("450.30")
        assert q.bid_size == 11 and q.ask_size == 13

    @pytest.mark.asyncio
    async def test_account_summary(self):
        c = _make_client(FakeGateway())
        s = await c.get_account_summary()
        assert s.net_liquidation == Decimal("25000.0")
        assert s.buying_power == Decimal("40000.0")

    @pytest.mark.asyncio
    async def test_positions_parses_option_and_equity(self):
        c = _make_client(FakeGateway())
        positions = await c.get_positions()
        assert len(positions) == 2
        opt = next(p for p in positions if p.strike != Decimal("0"))
        eq = next(p for p in positions if p.strike == Decimal("0"))
        assert opt.option_type == "put" and opt.underlying == "SPY" and opt.quantity == -1
        assert eq.symbol == "AAPL" and eq.quantity == 100


# ── Order placement ───────────────────────────────────────────────────────────────

class TestOrders:
    @pytest.mark.asyncio
    async def test_combo_uses_conidex_with_signed_ratios(self):
        gw = FakeGateway(order_status="Filled", filled=1, avg=1.50)
        c = _make_client(gw)
        result = await c.place_order(_credit_spread())
        assert result.status == "filled"
        body = gw.order_bodies[-1]["orders"][0]
        # One combo order, BUY side, with a conidex listing both legs.
        assert body["side"] == "BUY"
        assert body["orderType"] == "LMT"
        assert ";;;" in body["conidex"]
        # SELL leg gets a negative ratio, BUY leg positive.
        assert "/-1" in body["conidex"] and "/1" in body["conidex"]
        # Credit of 1.50 → negative net combo price.
        assert body["price"] == -1.50

    @pytest.mark.asyncio
    async def test_market_combo_has_no_price(self):
        gw = FakeGateway(filled=1)
        c = _make_client(gw)
        await c.place_order(_credit_spread(order_type="MKT"))
        body = gw.order_bodies[-1]["orders"][0]
        assert body["orderType"] == "MKT"
        assert "price" not in body

    @pytest.mark.asyncio
    async def test_single_leg_uses_conid_and_leg_side(self):
        gw = FakeGateway(filled=1, avg=2.0)
        c = _make_client(gw)
        single = SpreadOrder(
            strategy="flatten", underlying="SPY",
            legs=[SpreadLeg(symbol="SPY", strike=Decimal("450"),
                            expiration=date(2025, 1, 17), option_type="put",
                            action="BUY", quantity=1)],
            limit_price=Decimal("2.00"), order_type="LMT", time_in_force="DAY",
        )
        await c.place_order(single)
        body = gw.order_bodies[-1]["orders"][0]
        assert "conid" in body and "conidex" not in body
        assert body["side"] == "BUY"
        assert body["price"] == 2.00

    @pytest.mark.asyncio
    async def test_reply_confirmation_handshake(self):
        # First /orders response is a confirmation question; client must confirm.
        gw = FakeGateway(filled=1, reply_first=True)
        c = _make_client(gw)
        result = await c.place_order(_credit_spread())
        assert result.status == "filled"
        assert any("/iserver/reply/" in r.url.path for r in gw.requests)

    @pytest.mark.asyncio
    async def test_partial_fill_reported(self):
        gw = FakeGateway(order_status="Submitted", filled=3, avg=1.48)
        c = _make_client(gw)
        c._fill_timeout = lambda: 0          # force timeout path with partial fill
        result = await c.place_order(_credit_spread(q_short=5, q_long=5))
        assert result.status == "partial"
        assert result.filled_quantity == 3
        assert result.remaining_quantity == 2

    @pytest.mark.asyncio
    async def test_rejected_order(self):
        gw = FakeGateway(order_status="Rejected", filled=0)
        c = _make_client(gw)
        result = await c.place_order(_credit_spread())
        assert result.status == "rejected"


# ── Equity brackets ───────────────────────────────────────────────────────────────

class TestEquityBrackets:
    @pytest.mark.asyncio
    async def test_bracket_children_reference_parent_coid(self):
        gw = FakeGateway(order_status="Filled", filled=100, avg=180.0)
        c = _make_client(gw)
        result = await c.place_equity_order(
            "AAPL", 100, "BUY", order_type="limit",
            limit_price=180.0, stop=175.0, take_profit=190.0)
        assert result.status == "filled"
        orders = gw.order_bodies[-1]["orders"]
        assert len(orders) == 3
        parent, tp, sl = orders
        parent_coid = parent["cOID"]
        assert tp["parentId"] == parent_coid and sl["parentId"] == parent_coid
        assert tp["orderType"] == "LMT" and tp["side"] == "SELL" and tp["price"] == 190.0
        assert sl["orderType"] == "STP" and sl["side"] == "SELL" and sl["auxPrice"] == 175.0

    @pytest.mark.asyncio
    async def test_plain_equity_order_no_children(self):
        gw = FakeGateway(order_status="Filled", filled=10, avg=180.0)
        c = _make_client(gw)
        await c.place_equity_order("AAPL", 10, "BUY", order_type="market")
        orders = gw.order_bodies[-1]["orders"]
        assert len(orders) == 1
        assert orders[0]["orderType"] == "MKT"
