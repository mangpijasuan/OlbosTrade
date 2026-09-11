"""
Tests for the read-only deployment guard.

The hybrid tenancy model depends on the shared instance being structurally
unable to trade. "Structurally" is the load-bearing word: execution_mode=manual
and an armed kill switch are both runtime state a request can change, so
neither is a tenancy boundary.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker.read_only_broker import ExecutionDisabledError, ReadOnlyBroker


def _broker():
    b = MagicMock()
    b.place_order = AsyncMock(return_value="filled")
    b.place_equity_order = AsyncMock(return_value="filled")
    b.cancel_open_orders = AsyncMock(return_value=2)
    b.cancel_orders_by_id = AsyncMock(return_value=1)
    b.get_positions = AsyncMock(return_value=["a position"])
    b.get_account_summary = AsyncMock(return_value="summary")
    return b


@pytest.mark.asyncio
async def test_place_order_is_refused():
    ro = ReadOnlyBroker(_broker())
    with pytest.raises(ExecutionDisabledError, match="EXECUTION_ENABLED=false"):
        await ro.place_order(MagicMock())


@pytest.mark.asyncio
async def test_place_equity_order_is_refused():
    """The equity path is a separate method — blocking only place_order would
    leave every equity entry open."""
    ro = ReadOnlyBroker(_broker())
    with pytest.raises(ExecutionDisabledError):
        await ro.place_equity_order("AAPL", 10, "buy")


@pytest.mark.asyncio
async def test_reads_pass_straight_through():
    """The shared instance still needs live market and account data — it exists
    to serve signals, which cannot be produced from nothing."""
    inner = _broker()
    ro = ReadOnlyBroker(inner)
    assert await ro.get_positions() == ["a position"]
    assert await ro.get_account_summary() == "summary"
    inner.get_positions.assert_awaited_once()


@pytest.mark.asyncio
async def test_closing_and_cancelling_are_still_allowed():
    """
    Deliberate carve-out. Cancels and the kill switch's flattening only ever
    REDUCE exposure; a safety flag that stopped a desk closing a position it
    somehow holds would be a worse failure than the one being guarded against.
    """
    inner = _broker()
    ro = ReadOnlyBroker(inner)
    assert await ro.cancel_open_orders("SPY") == 2
    assert await ro.cancel_orders_by_id(["1"]) == 1


def test_unknown_attributes_proxy_to_the_inner_broker():
    inner = _broker()
    inner.some_new_method = "value"
    assert ReadOnlyBroker(inner).some_new_method == "value"


# ── the factory is the chokepoint ────────────────────────────────────────────

def test_factory_wraps_when_execution_is_disabled():
    """
    Gating _execute_signal alone would miss position_rotation's entry and close
    paths, trade_desk's manual close, and the kill switch's flattening. They all
    reach the broker through get_broker(), so the wrap belongs there.
    """
    from app.broker import broker_factory

    broker_factory.reset_broker()
    fake = _broker()
    with patch("app.broker.alpaca_client.AlpacaClient", return_value=fake), \
         patch.object(broker_factory.__dict__.get("logger"), "critical", MagicMock()):
        from app.core.config import settings
        with patch.object(settings, "broker", "alpaca"), \
             patch.object(settings, "execution_enabled", False):
            got = broker_factory.get_broker()
    broker_factory.reset_broker()
    assert isinstance(got, ReadOnlyBroker)


def test_factory_does_not_wrap_when_execution_is_enabled():
    """Existing single-operator installs must be unaffected — default is True."""
    from app.broker import broker_factory

    broker_factory.reset_broker()
    fake = _broker()
    with patch("app.broker.alpaca_client.AlpacaClient", return_value=fake):
        from app.core.config import settings
        with patch.object(settings, "broker", "alpaca"), \
             patch.object(settings, "execution_enabled", True):
            got = broker_factory.get_broker()
    broker_factory.reset_broker()
    assert got is fake
    assert not isinstance(got, ReadOnlyBroker)
