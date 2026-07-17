"""
Regression coverage for the shared account-value helper.

Previously "get real account value, fall back to starting_capital" was
duplicated 3x, with 2 of 4 call sites (main.py equity trade-plan sizing,
portfolio.py heat %) hardcoded to the static config value instead of ever
reaching the broker. This is the single function all four now share.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.services.account_state import get_account_value


@pytest.mark.asyncio
async def test_returns_live_net_liquidation():
    broker = MagicMock()
    broker.get_account_summary = AsyncMock(
        return_value=MagicMock(net_liquidation=64231.50)
    )
    with patch("app.broker.broker_factory.get_broker", return_value=broker):
        value = await get_account_value()
    assert value == 64231.50


@pytest.mark.asyncio
async def test_falls_back_to_starting_capital_when_broker_unreachable():
    with patch("app.broker.broker_factory.get_broker", side_effect=ConnectionError("down")):
        value = await get_account_value()
    assert value == settings.starting_capital


@pytest.mark.asyncio
async def test_falls_back_when_net_liquidation_is_none():
    broker = MagicMock()
    broker.get_account_summary = AsyncMock(return_value=MagicMock(net_liquidation=None))
    with patch("app.broker.broker_factory.get_broker", return_value=broker):
        value = await get_account_value()
    assert value == settings.starting_capital
