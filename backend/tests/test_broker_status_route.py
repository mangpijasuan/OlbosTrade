"""
Tests for GET /api/market/broker — connectivity/paper-mode detection must
work correctly per-broker, not just for IBKR's socket-based connection model.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.routes.market_data import get_broker_status


@pytest.mark.asyncio
async def test_ibkr_connected_when_socket_and_flag_both_true():
    broker = MagicMock()
    broker.supports_options = True
    broker.supports_equities = True
    broker._connected = True
    broker.ib = MagicMock()
    broker.ib.isConnected.return_value = True

    with patch("app.api.routes.market_data.get_broker", return_value=broker), \
         patch("app.api.routes.market_data.settings.broker", "ibkr"), \
         patch("app.api.routes.market_data.settings.ibkr_trading_mode", "paper"), \
         patch("app.api.routes.market_data.settings.ibkr_port", 7497):
        result = await get_broker_status()

    assert result["status"] == "connected"
    assert result["paper_mode"] is True


@pytest.mark.asyncio
async def test_ibkr_disconnected_when_socket_reports_false_despite_flag():
    """A hardcoded `_connected=True` must not paper over a dropped socket —
    isConnected() is the real signal."""
    broker = MagicMock()
    broker.supports_options = True
    broker.supports_equities = True
    broker._connected = True
    broker.ib = MagicMock()
    broker.ib.isConnected.return_value = False

    with patch("app.api.routes.market_data.get_broker", return_value=broker), \
         patch("app.api.routes.market_data.settings.broker", "ibkr"):
        result = await get_broker_status()

    assert result["status"] == "disconnected"


@pytest.mark.asyncio
async def test_alpaca_connected_via_flag_alone_no_socket():
    """Alpaca has no `.ib` socket object — connectivity is just its own
    _connected flag, not a broken isConnected() lookup."""
    broker = MagicMock(spec=["supports_options", "supports_equities", "_connected"])
    broker.supports_options = True
    broker.supports_equities = True
    broker._connected = True

    with patch("app.api.routes.market_data.get_broker", return_value=broker), \
         patch("app.api.routes.market_data.settings.broker", "alpaca"), \
         patch("app.api.routes.market_data.settings.alpaca_base_url", "https://paper-api.alpaca.markets"):
        result = await get_broker_status()

    assert result["status"] == "connected"
    assert result["paper_mode"] is True


@pytest.mark.asyncio
async def test_alpaca_live_base_url_is_not_paper_mode():
    broker = MagicMock(spec=["supports_options", "supports_equities", "_connected"])
    broker.supports_options = True
    broker.supports_equities = True
    broker._connected = True

    with patch("app.api.routes.market_data.get_broker", return_value=broker), \
         patch("app.api.routes.market_data.settings.broker", "alpaca"), \
         patch("app.api.routes.market_data.settings.alpaca_base_url", "https://api.alpaca.markets"):
        result = await get_broker_status()

    assert result["paper_mode"] is False


@pytest.mark.asyncio
async def test_broker_error_falls_back_to_error_status():
    with patch("app.api.routes.market_data.get_broker", side_effect=RuntimeError("boom")), \
         patch("app.api.routes.market_data.settings.broker", "alpaca"):
        result = await get_broker_status()

    assert result["status"] == "error"
    assert "boom" in result["error"]
