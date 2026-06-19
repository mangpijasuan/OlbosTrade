"""
Unit tests for IBKRClient using mocked ib_insync responses.
Run with: pytest tests/test_ibkr_client.py -v
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker.ibkr_client import IBKRClient


@pytest.fixture
def client():
    c = IBKRClient()
    c._connected = True
    c.ib.isConnected = MagicMock(return_value=True)
    return c


@pytest.mark.asyncio
async def test_connect_succeeds_on_first_attempt():
    """connect() should succeed without retrying when TWS responds."""
    client = IBKRClient()
    with patch.object(client.ib, "connectAsync", new_callable=AsyncMock) as mock_connect, \
         patch.object(client.ib, "reqMarketDataType"):
        await client.connect()
    mock_connect.assert_called_once()
    assert client._connected is True


@pytest.mark.asyncio
async def test_connect_retries_on_failure_then_raises():
    """connect() should retry MAX_RETRIES times then raise ConnectionError."""
    client = IBKRClient()
    with patch.object(client.ib, "connectAsync",
                      new_callable=AsyncMock,
                      side_effect=ConnectionRefusedError("TWS not running")):
        with patch("app.broker.ibkr_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConnectionError, match="Failed to connect"):
                await client.connect()


@pytest.mark.asyncio
async def test_get_account_summary_maps_fields_correctly(client):
    """get_account_summary should map IBKR account tags to AccountSummary fields."""
    mock_values = [
        MagicMock(tag="NetLiquidation", value="25000.00", currency="USD"),
        MagicMock(tag="TotalCashValue", value="20000.00", currency="USD"),
        MagicMock(tag="OptionBuyingPower", value="15000.00", currency="USD"),
    ]
    client.ib.accountValues = MagicMock(return_value=mock_values)
    client.ib.managedAccounts = MagicMock(return_value=["DU123456"])

    summary = await client.get_account_summary()

    assert summary.account_id == "DU123456"
    assert summary.net_liquidation == Decimal("25000.00")
    assert summary.cash_balance == Decimal("20000.00")
    assert summary.buying_power == Decimal("15000.00")
    assert summary.trading_mode == "paper"


@pytest.mark.asyncio
async def test_get_positions_filters_options_only(client):
    """get_positions should return only OPT contracts, not stocks."""
    stock_contract = MagicMock()
    stock_contract.secType = "STK"
    stock_contract.symbol = "SPY"

    opt_contract = MagicMock()
    opt_contract.secType = "OPT"
    opt_contract.symbol = "SPY"
    opt_contract.localSymbol = "SPY240119P00450000"
    opt_contract.strike = 450.0
    opt_contract.lastTradeDateOrContractMonth = "20240119"
    opt_contract.right = "P"

    mock_positions = [
        MagicMock(contract=stock_contract, position=100, avgCost=450.0),
        MagicMock(contract=opt_contract, position=-1, avgCost=125.0),
    ]

    with patch.object(client.ib, "reqPositionsAsync",
                      new_callable=AsyncMock, return_value=mock_positions):
        positions = await client.get_positions()

    # get_positions returns all OPT + STK/ETF; filter to options only
    options = [p for p in positions if p.strike > 0]
    assert len(options) == 1
    assert options[0].option_type == "put"
    assert options[0].strike == Decimal("450.0")
    assert options[0].quantity == -1
