"""
Tests for the Alpaca broker client — focused on the get_positions parsing fix.

get_equity_positions returns raw Alpaca position dicts; get_positions previously
iterated them as if they were objects (ep.symbol), raising AttributeError and
breaking position reads (and therefore the kill-switch flatten) for the whole app.

Run with: pytest tests/test_alpaca_client.py -v
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.broker.alpaca_client import AlpacaClient


@pytest.mark.asyncio
async def test_get_positions_parses_raw_dicts():
    client = AlpacaClient()
    client.get_equity_positions = AsyncMock(return_value=[
        {"symbol": "AAPL", "qty": "100", "avg_entry_price": "180.50",
         "current_price": "185.00", "unrealized_pl": "450.00"},
        {"symbol": "TSLA", "qty": "-50", "avg_entry_price": "240.00",
         "current_price": "235.00", "unrealized_pl": "250.00"},
    ])

    positions = await client.get_positions()

    assert len(positions) == 2
    aapl = positions[0]
    assert aapl.symbol == "AAPL"
    assert aapl.quantity == 100
    assert aapl.avg_cost == Decimal("180.50")
    assert aapl.strike == Decimal("0")           # equity sentinel
    assert positions[1].quantity == -50          # short position preserved


@pytest.mark.asyncio
async def test_get_positions_empty():
    client = AlpacaClient()
    client.get_equity_positions = AsyncMock(return_value=[])
    assert await client.get_positions() == []
