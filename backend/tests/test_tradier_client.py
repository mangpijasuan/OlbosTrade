"""
Unit tests for TradierClient using mocked httpx responses.
Run with: pytest tests/test_tradier_client.py -v
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker.tradier_client import TradierClient


MOCK_CHAIN_RESPONSE = {
    "options": {
        "option": [
            {
                "symbol": "SPY240119P00450000",
                "option_type": "put",
                "strike": 450.0,
                "bid": 1.20,
                "ask": 1.30,
                "last": 1.25,
                "volume": 5000,
                "open_interest": 12000,
                "greeks": {
                    "delta": -0.20,
                    "gamma": 0.015,
                    "theta": -0.08,
                    "vega": 0.30,
                    "mid_iv": 0.22,
                },
            },
            {
                "symbol": "SPY240119C00460000",
                "option_type": "call",
                "strike": 460.0,
                "bid": 1.10,
                "ask": 1.20,
                "last": 1.15,
                "volume": 3000,
                "open_interest": 8000,
                "greeks": {
                    "delta": 0.22,
                    "gamma": 0.014,
                    "theta": -0.07,
                    "vega": 0.28,
                    "mid_iv": 0.21,
                },
            },
        ]
    }
}

MOCK_QUOTE_RESPONSE = {
    "quotes": {"quote": {"last": 455.50}}
}

MOCK_ACCOUNT_RESPONSE = {
    "balances": {
        "account_number": "TEST123",
        "total_equity": 25000.00,
        "total_cash": 20000.00,
        "option_buying_power": 15000.00,
    }
}


class _ConcreteTradierClient(TradierClient):
    """Minimal concrete subclass that satisfies new abstract methods added to BrokerInterface."""
    async def get_bars(self, *a, **kw): return []
    async def get_latest_quote(self, *a, **kw): return None
    async def place_equity_order(self, *a, **kw): return None
    def supports_equities(self): return False
    def supports_options(self): return True


@pytest.fixture
def client():
    return _ConcreteTradierClient()


@pytest.mark.asyncio
async def test_get_options_chain_returns_correct_structure(client):
    """get_options_chain should return OptionsChain with calls and puts."""
    async def mock_get(path, params=None):
        if "chains" in path:
            return MOCK_CHAIN_RESPONSE
        return MOCK_QUOTE_RESPONSE

    with patch.object(client, "_get", side_effect=mock_get):
        chain = await client.get_options_chain("SPY", "2024-01-19")

    assert chain.underlying == "SPY"
    assert chain.expiration == date(2024, 1, 19)
    assert len(chain.puts) == 1
    assert len(chain.calls) == 1
    assert chain.underlying_price == Decimal("455.50")


@pytest.mark.asyncio
async def test_get_greeks_returns_correct_values(client):
    """get_greeks should return Greeks matching the requested contract."""
    async def mock_get(path, params=None):
        if "chains" in path:
            return MOCK_CHAIN_RESPONSE
        return MOCK_QUOTE_RESPONSE

    with patch.object(client, "_get", side_effect=mock_get):
        greeks = await client.get_greeks("SPY", 450.0, "2024-01-19", "put")

    assert greeks.delta == pytest.approx(-0.20)
    assert greeks.implied_vol == pytest.approx(0.22)
    assert greeks.theta < 0


@pytest.mark.asyncio
async def test_get_account_summary_returns_balances(client):
    """get_account_summary should map Tradier balance fields correctly."""
    with patch.object(client, "_get", return_value=MOCK_ACCOUNT_RESPONSE):
        summary = await client.get_account_summary()

    assert summary.account_id == "TEST123"
    assert summary.net_liquidation == Decimal("25000.00")
    assert summary.cash_balance == Decimal("20000.00")
    assert summary.buying_power == Decimal("15000.00")
    assert summary.trading_mode == "sandbox"
