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

    mock_items = [
        MagicMock(contract=stock_contract, position=100, averageCost=450.0,
                   marketPrice=455.0, unrealizedPNL=500.0),
        MagicMock(contract=opt_contract, position=-1, averageCost=125.0,
                   marketPrice=110.0, unrealizedPNL=15.0),
    ]

    with patch.object(client.ib, "portfolio", return_value=mock_items):
        positions = await client.get_positions()

    # get_positions returns all OPT + STK/ETF; filter to options only
    options = [p for p in positions if p.strike > 0]
    assert len(options) == 1
    assert options[0].option_type == "put"
    assert options[0].strike == Decimal("450.0")
    assert options[0].quantity == -1


@pytest.mark.asyncio
async def test_get_positions_carries_live_price_and_unrealized_pnl(client):
    """current_price/unrealized_pnl must come from IBKR's own portfolio() marks —
    this is what MFE/MAE excursion tracking (and the journal's recorded values)
    depend on; reqPositionsAsync() never carried these fields at all."""
    stock_contract = MagicMock()
    stock_contract.secType = "STK"
    stock_contract.symbol = "AAPL"

    mock_items = [
        MagicMock(contract=stock_contract, position=10, averageCost=150.0,
                   marketPrice=162.5, unrealizedPNL=125.0),
    ]

    with patch.object(client.ib, "portfolio", return_value=mock_items):
        positions = await client.get_positions()

    assert len(positions) == 1
    assert positions[0].current_price == Decimal("162.5")
    assert positions[0].unrealized_pnl == Decimal("125.0")


@pytest.mark.asyncio
async def test_get_equity_positions_carries_price_and_pnl(client):
    stock_contract = MagicMock()
    stock_contract.secType = "STK"
    stock_contract.symbol = "MSFT"

    mock_items = [
        MagicMock(contract=stock_contract, position=5, averageCost=300.0,
                   marketPrice=310.0, unrealizedPNL=50.0),
    ]

    with patch.object(client.ib, "portfolio", return_value=mock_items):
        equity_positions = await client.get_equity_positions()

    assert len(equity_positions) == 1
    assert equity_positions[0].current_price == Decimal("310.0")
    assert equity_positions[0].unrealized_pnl == Decimal("50.0")
    assert equity_positions[0].market_value == Decimal("1550.0")


# ── cancel_open_orders (manual close: clear a bracket's stop/target legs) ─────

@pytest.mark.asyncio
async def test_cancel_open_orders_only_cancels_matching_symbol(client):
    aapl_trade = MagicMock()
    aapl_trade.contract.symbol = "AAPL"
    msft_trade = MagicMock()
    msft_trade.contract.symbol = "MSFT"
    client.ib.openTrades = MagicMock(return_value=[aapl_trade, msft_trade])
    client.ib.cancelOrder = MagicMock()

    with patch("app.broker.ibkr_client.asyncio.sleep", new_callable=AsyncMock):
        count = await client.cancel_open_orders("aapl")  # lowercase input

    assert count == 1
    client.ib.cancelOrder.assert_called_once_with(aapl_trade.order)


@pytest.mark.asyncio
async def test_cancel_open_orders_returns_zero_when_none_match(client):
    other_trade = MagicMock()
    other_trade.contract.symbol = "TSLA"
    client.ib.openTrades = MagicMock(return_value=[other_trade])
    client.ib.cancelOrder = MagicMock()

    count = await client.cancel_open_orders("AAPL")

    assert count == 0
    client.ib.cancelOrder.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_open_orders_continues_after_one_cancel_fails(client):
    """One order's cancel throwing must not stop the rest from being cancelled."""
    bad_trade = MagicMock()
    bad_trade.contract.symbol = "AAPL"
    bad_trade.order = MagicMock(orderId=1)
    good_trade = MagicMock()
    good_trade.contract.symbol = "AAPL"
    good_trade.order = MagicMock(orderId=2)
    client.ib.openTrades = MagicMock(return_value=[bad_trade, good_trade])
    client.ib.cancelOrder = MagicMock(side_effect=[RuntimeError("boom"), None])

    with patch("app.broker.ibkr_client.asyncio.sleep", new_callable=AsyncMock):
        count = await client.cancel_open_orders("AAPL")

    assert count == 1  # only the second (successful) cancel counted
    assert client.ib.cancelOrder.call_count == 2
