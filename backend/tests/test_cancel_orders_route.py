"""
Cancelling resting orders by id.

The one action in this file that can *increase* risk rather than reduce it:
a resting stop is protection, and cancelling the wrong id strips a live
position. So the guard — never touch an order whose symbol has a position —
is what these tests are mostly about.

Context (2026-08-29): 20 orphaned orders across ASML/EXC/INTU/MU were
cancelled in TWS and all 20 were still live on the next refreshed read, with
no visible error. This route reports IBKR's per-order answer and verifies
against a fresh read instead of trusting the send.

Run with: pytest tests/test_cancel_orders_route.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes.portfolio import CancelOrdersRequest, cancel_orders


def _book(orders, source="refreshed"):
    return {"source": source, "orders": orders, "order_count": len(orders)}


def _o(oid, sym, protective=True):
    return {"order_id": oid, "symbol": sym, "is_protective": protective,
            "remaining": 10.0, "status": "PreSubmitted"}


def _broker(before, after=None, held=("MRVL",), cancel_result=None):
    b = MagicMock()
    b.get_open_orders = AsyncMock(side_effect=[_book(before), _book(after if after is not None else before)])
    b.get_positions = AsyncMock(
        return_value=[SimpleNamespace(symbol=s, underlying=s) for s in held])
    b.cancel_orders_by_id = AsyncMock(
        return_value=cancel_result if cancel_result is not None
        else [{"order_id": o["order_id"], "result": "cancel_sent", "symbol": o["symbol"]}
              for o in before])
    return b


@pytest.mark.asyncio
async def test_refuses_to_cancel_an_order_protecting_a_live_position():
    """The whole point. A fat-fingered id must not strip MRVL's bracket."""
    b = _broker([_o(1, "EXC"), _o(2, "MRVL")], held=("MRVL",))
    with patch("app.broker.broker_factory.get_broker", return_value=b):
        with pytest.raises(HTTPException) as exc:
            await cancel_orders(CancelOrdersRequest(order_ids=[1, 2]))
    assert exc.value.status_code == 409
    assert exc.value.detail["protected_order_ids"] == [2]
    # Rejected as a group — a partial cancel leaving one leg of a live
    # bracket would be worse than doing nothing.
    b.cancel_orders_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_cancels_orphans_and_verifies_against_a_fresh_read():
    b = _broker([_o(1, "EXC"), _o(2, "INTU")], after=[], held=("MRVL",))
    with patch("app.broker.broker_factory.get_broker", return_value=b):
        out = await cancel_orders(CancelOrdersRequest(order_ids=[1, 2]))
    assert out["confirmed_cancelled"] == 2
    assert out["still_open"] == 0
    assert all(r["verified"] == "gone from the order book" for r in out["results"])


@pytest.mark.asyncio
async def test_reports_orders_ibkr_did_not_actually_cancel():
    """The exact failure seen in TWS: the send appears fine, the order stays.
    A count of 'sent' must never be reported as success."""
    before = [_o(1, "EXC"), _o(2, "INTU")]
    b = _broker(before, after=before, held=("MRVL",))   # nothing disappeared
    with patch("app.broker.broker_factory.get_broker", return_value=b):
        out = await cancel_orders(CancelOrdersRequest(order_ids=[1, 2]))
    assert out["confirmed_cancelled"] == 0
    assert out["still_open"] == 2
    assert all("STILL OPEN" in r["verified"] for r in out["results"])


@pytest.mark.asyncio
async def test_refuses_when_the_order_book_came_from_cache():
    """A cache fall-back cannot prove an order is unprotected."""
    b = MagicMock()
    b.get_open_orders = AsyncMock(return_value=_book([], source="cache_after_refresh_failed"))
    b.cancel_orders_by_id = AsyncMock()
    with patch("app.broker.broker_factory.get_broker", return_value=b):
        with pytest.raises(HTTPException) as exc:
            await cancel_orders(CancelOrdersRequest(order_ids=[1]))
    assert exc.value.status_code == 503
    b.cancel_orders_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_empty_id_list_is_rejected():
    with pytest.raises(HTTPException) as exc:
        await cancel_orders(CancelOrdersRequest(order_ids=[]))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_unknown_id_is_reported_not_silently_counted():
    b = _broker([_o(1, "EXC")], after=[], held=("MRVL",),
                cancel_result=[{"order_id": 99, "result": "not_found",
                                "detail": "not in the broker's open-order book"}])
    with patch("app.broker.broker_factory.get_broker", return_value=b):
        out = await cancel_orders(CancelOrdersRequest(order_ids=[99]))
    assert out["results"][0]["result"] == "not_found"
