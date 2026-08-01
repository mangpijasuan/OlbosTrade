"""
Unit tests for AlpacaClient — HTTP calls are mocked (no live/paper Alpaca
account required). Covers the OCC symbol parsing/building helpers, status
mapping, and the request-building logic for each BrokerInterface method.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker.alpaca_client import (
    AlpacaClient,
    _build_occ_symbol,
    _map_equity_status,
    _map_spread_status,
    _parse_occ_symbol,
)
from app.broker.broker_interface import SpreadLeg, SpreadOrder


@pytest.fixture
def client(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "alpaca_api_key", "test-key")
    monkeypatch.setattr(settings, "alpaca_secret_key", "test-secret")
    monkeypatch.setattr(settings, "alpaca_base_url", "https://paper-api.alpaca.markets")
    return AlpacaClient()


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _patch_http_client(get=None, post=None, delete=None):
    """Patches httpx.AsyncClient so `async with httpx.AsyncClient(...) as c`
    yields an object whose .get/.post/.delete are AsyncMocks returning the
    given mock response objects (each call returns the same response)."""
    instance = AsyncMock()
    if get is not None:
        instance.get = AsyncMock(return_value=get)
    if post is not None:
        instance.post = AsyncMock(return_value=post)
    if delete is not None:
        instance.delete = AsyncMock(return_value=delete)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=instance)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("app.broker.alpaca_client.httpx.AsyncClient", return_value=ctx), instance


# ── OCC symbol helpers ──────────────────────────────────────────────────────

def test_parse_occ_symbol_call():
    underlying, exp, opt_type, strike = _parse_occ_symbol("AAPL240119C00190000")
    assert underlying == "AAPL"
    assert exp == date(2024, 1, 19)
    assert opt_type == "call"
    assert strike == Decimal("190.000")


def test_parse_occ_symbol_put_multi_char_root():
    underlying, exp, opt_type, strike = _parse_occ_symbol("SPY240119P00450500")
    assert underlying == "SPY"
    assert opt_type == "put"
    assert strike == Decimal("450.500")


def test_build_occ_symbol_round_trips_with_parse():
    occ = _build_occ_symbol("AAPL", "2024-01-19", "call", 190.0)
    assert occ == "AAPL240119C00190000"
    underlying, exp, opt_type, strike = _parse_occ_symbol(occ)
    assert underlying == "AAPL"
    assert exp == date(2024, 1, 19)
    assert opt_type == "call"
    assert strike == Decimal("190.000")


def test_build_occ_symbol_put():
    occ = _build_occ_symbol("SPY", "2024-03-15", "put", 450.5)
    assert occ == "SPY240315P00450500"


# ── Status mapping ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("alpaca_status,expected", [
    ("filled", "filled"),
    ("canceled", "cancelled"),
    ("expired", "cancelled"),
    ("rejected", "rejected"),
    ("pending_cancel", "pending"),
    ("new", "submitted"),
    ("partially_filled", "submitted"),
])
def test_map_equity_status(alpaca_status, expected):
    assert _map_equity_status(alpaca_status) == expected


@pytest.mark.parametrize("alpaca_status,expected", [
    ("filled", "filled"),
    ("partially_filled", "partial"),
    ("canceled", "cancelled"),
    ("rejected", "rejected"),
    ("new", "submitted"),
])
def test_map_spread_status(alpaca_status, expected):
    assert _map_spread_status(alpaca_status) == expected


# ── get_account_summary ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_account_summary_maps_fields(client):
    payload = {
        "account_number": "PA123456",
        "equity": "25000.00",
        "cash": "20000.00",
        "buying_power": "15000.00",
        "daytrade_count": 1,
        "pattern_day_trader": False,
    }
    patcher, _ = _patch_http_client(get=_mock_response(payload))
    with patcher:
        summary = await client.get_account_summary()

    assert summary.account_id == "PA123456"
    assert summary.net_liquidation == Decimal("25000.00")
    assert summary.cash_balance == Decimal("20000.00")
    assert summary.buying_power == Decimal("15000.00")
    assert summary.trading_mode == "paper"
    assert summary.day_trades_remaining == 2  # 3 - 1


@pytest.mark.asyncio
async def test_get_account_summary_pattern_day_trader_has_no_remaining_cap(client):
    payload = {
        "account_number": "PA1", "equity": "1", "cash": "1", "buying_power": "1",
        "daytrade_count": 10, "pattern_day_trader": True,
    }
    patcher, _ = _patch_http_client(get=_mock_response(payload))
    with patcher:
        summary = await client.get_account_summary()
    assert summary.day_trades_remaining is None


# ── get_positions ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_positions_maps_equity_with_strike_zero_sentinel(client):
    payload = [{
        "symbol": "AAPL", "asset_class": "us_equity", "qty": "10", "side": "long",
        "avg_entry_price": "150.00", "current_price": "155.00", "unrealized_pl": "50.00",
    }]
    patcher, _ = _patch_http_client(get=_mock_response(payload))
    with patcher:
        positions = await client.get_positions()

    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "AAPL"
    assert p.strike == Decimal("0")
    assert p.quantity == 10
    assert p.current_price == Decimal("155.00")
    assert p.unrealized_pnl == Decimal("50.00")


@pytest.mark.asyncio
async def test_get_positions_short_equity_is_negative_quantity(client):
    payload = [{
        "symbol": "TSLA", "asset_class": "us_equity", "qty": "5", "side": "short",
        "avg_entry_price": "200.00", "current_price": None, "unrealized_pl": None,
    }]
    patcher, _ = _patch_http_client(get=_mock_response(payload))
    with patcher:
        positions = await client.get_positions()
    assert positions[0].quantity == -5


@pytest.mark.asyncio
async def test_get_positions_maps_option_via_occ_symbol(client):
    payload = [{
        "symbol": "AAPL240119C00190000", "asset_class": "us_option", "qty": "1", "side": "long",
        "avg_entry_price": "2.50", "current_price": "3.00", "unrealized_pl": "50.00",
    }]
    patcher, _ = _patch_http_client(get=_mock_response(payload))
    with patcher:
        positions = await client.get_positions()

    p = positions[0]
    assert p.underlying == "AAPL"
    assert p.strike == Decimal("190.000")
    assert p.option_type == "call"
    assert p.expiration == date(2024, 1, 19)


# ── place_equity_order ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_place_equity_order_market_buy(client):
    payload = {"id": "order-1", "status": "new"}
    patcher, instance = _patch_http_client(post=_mock_response(payload))
    with patcher:
        result = await client.place_equity_order(ticker="aapl", qty=10, side="BUY")

    assert result.order_id == "order-1"
    assert result.status == "submitted"
    body = instance.post.call_args.kwargs["json"]
    assert body["symbol"] == "AAPL"
    assert body["side"] == "buy"
    assert body["type"] == "market"
    assert "order_class" not in body


@pytest.mark.asyncio
async def test_place_equity_order_with_bracket_builds_order_class(client):
    payload = {"id": "order-2", "status": "filled", "filled_avg_price": "150.00"}
    patcher, instance = _patch_http_client(post=_mock_response(payload))
    with patcher:
        result = await client.place_equity_order(
            ticker="AAPL", qty=10, side="BUY", order_type="limit",
            limit_price=150.0, stop=145.0, take_profit=160.0,
        )

    assert result.status == "filled"
    assert result.fill_price == Decimal("150.00")
    body = instance.post.call_args.kwargs["json"]
    assert body["order_class"] == "bracket"
    assert body["take_profit"] == {"limit_price": "160.0"}
    assert body["stop_loss"] == {"stop_price": "145.0"}


# ── place_order (multi-leg spread) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_place_order_builds_mleg_payload(client):
    spread = SpreadOrder(
        strategy="bull_put_spread",
        underlying="SPY",
        legs=[
            SpreadLeg(symbol="SPY", strike=Decimal("450"), expiration=date(2024, 1, 19),
                      option_type="put", action="SELL", quantity=1),
            SpreadLeg(symbol="SPY", strike=Decimal("445"), expiration=date(2024, 1, 19),
                      option_type="put", action="BUY", quantity=1),
        ],
        limit_price=Decimal("1.50"),
    )
    payload = {"id": "order-3", "status": "new"}
    patcher, instance = _patch_http_client(post=_mock_response(payload))
    with patcher:
        result = await client.place_order(spread)

    assert result.order_id == "order-3"
    body = instance.post.call_args.kwargs["json"]
    assert body["order_class"] == "mleg"
    assert len(body["legs"]) == 2
    assert body["legs"][0]["symbol"] == "SPY240119P00450000"
    assert body["legs"][0]["side"] == "sell"
    assert body["legs"][1]["symbol"] == "SPY240119P00445000"
    assert body["legs"][1]["side"] == "buy"


# ── cancel_open_orders ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_open_orders_cancels_each_matching_order(client):
    open_orders = [{"id": "o1"}, {"id": "o2"}]
    patcher, instance = _patch_http_client(
        get=_mock_response(open_orders), delete=_mock_response(None, status_code=204),
    )
    with patcher:
        count = await client.cancel_open_orders("aapl")

    assert count == 2
    assert instance.delete.await_count == 2


@pytest.mark.asyncio
async def test_cancel_open_orders_continues_after_one_failure(client):
    open_orders = [{"id": "o1"}, {"id": "o2"}]

    async def _delete_side_effect(url, headers=None):
        if "o1" in url:
            raise RuntimeError("network error")
        resp = MagicMock()
        resp.status_code = 204
        return resp

    patcher, instance = _patch_http_client(get=_mock_response(open_orders))
    with patcher:
        instance.delete = AsyncMock(side_effect=_delete_side_effect)
        count = await client.cancel_open_orders("AAPL")

    assert count == 1


@pytest.mark.asyncio
async def test_cancel_open_orders_zero_when_none_open(client):
    patcher, _ = _patch_http_client(get=_mock_response([]))
    with patcher:
        count = await client.cancel_open_orders("AAPL")
    assert count == 0
