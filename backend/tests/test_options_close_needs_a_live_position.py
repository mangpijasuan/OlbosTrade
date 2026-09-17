"""
close_options_trade() refuses to "close" a position the broker is not holding.

Everything it submits is read from the DB Trade row — strikes, expiration,
quantity. A closing combo for a position that does not exist is an OPENING
trade in the opposite direction: it CREATES exposure instead of removing it.

That is reachable. paper_trade.py emits DB-only rows (source="db_only",
tracked=True) for open Trade rows with no matching broker position, and they
carry a valid id and a valid spread_type, so they look exactly like a closeable
position to every caller.

close_equity_trade() has guarded this since 2026-08-26 — it sources side and
size from get_equity_positions() and raises "already flat at the broker" when
the symbol is not held, after DB/broker quantity drift was root-caused in
production. The options path had no equivalent until PR #64. These tests pin
the asymmetry closed.

The guard is deliberately COARSE: any live, non-zero option position on the
underlying. It catches "there is nothing here", which is the hazard, without
matching leg-by-leg — strike and expiration types vary across broker adapters,
and an over-strict comparison would refuse legitimate risk-REDUCING closes,
which is its own harm. These tests assert that looseness on purpose.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.position_rotation import close_options_trade


def _trade():
    return SimpleNamespace(
        id=uuid4(), underlying="SPY", spread_type="put", quantity=1,
        short_strike=Decimal("400"), long_strike=Decimal("395"),
        expiration=date(2026, 12, 18), strategy="bull_put",
    )


def _option(underlying="SPY", qty=-1, asset_type="option"):
    return SimpleNamespace(
        symbol=f"{underlying}   261218P00400000", underlying=underlying,
        strike=Decimal("400"), expiration=date(2026, 12, 18), option_type="put",
        quantity=qty, avg_cost=Decimal("1.0"), asset_type=asset_type,
    )


def _broker(positions):
    b = SimpleNamespace()
    b.get_positions = AsyncMock(return_value=positions)
    b.cancel_open_orders = AsyncMock(return_value=0)
    b.place_order = AsyncMock(return_value=SimpleNamespace(
        status="filled", fill_price=Decimal("1.0"), order_id="x",
    ))
    return b


@pytest.mark.asyncio
async def test_it_refuses_when_the_broker_holds_nothing():
    """The db_only case: an open DB row, a flat broker."""
    broker = _broker([])

    with pytest.raises(RuntimeError, match="no live options position"):
        await close_options_trade(_trade(), broker=broker, closed_by="manual")

    # The point of the guard: nothing was sent.
    broker.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_it_refuses_when_the_only_position_is_a_different_underlying():
    broker = _broker([_option(underlying="QQQ")])

    with pytest.raises(RuntimeError, match="no live options position"):
        await close_options_trade(_trade(), broker=broker, closed_by="manual")
    broker.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_zero_quantity_row_does_not_count_as_held():
    """IBKR returns zero-quantity rows; they are not positions."""
    broker = _broker([_option(qty=0)])

    with pytest.raises(RuntimeError, match="no live options position"):
        await close_options_trade(_trade(), broker=broker, closed_by="manual")
    broker.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_equity_row_on_the_same_underlying_does_not_count():
    """Holding SPY shares is not holding a SPY spread."""
    broker = _broker([_option(asset_type="equity")])

    with pytest.raises(RuntimeError, match="no live options position"):
        await close_options_trade(_trade(), broker=broker, closed_by="manual")
    broker.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_it_proceeds_when_the_position_is_actually_held():
    """The guard must not block a real close — that would be its own harm."""
    broker = _broker([_option()])

    await close_options_trade(_trade(), broker=broker, closed_by="manual")

    broker.place_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_guard_is_coarse_on_purpose():
    """A held option on the underlying is enough, even at another strike.

    Matching leg-by-leg would refuse legitimate risk-reducing closes whenever
    strike or expiration types differ across broker adapters. Blocking a close
    is not the safe direction.
    """
    other_strike = _option()
    other_strike.strike = Decimal("380")
    broker = _broker([other_strike])

    await close_options_trade(_trade(), broker=broker, closed_by="manual")

    broker.place_order.assert_awaited_once()
