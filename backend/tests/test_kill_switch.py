"""
Kill switch tests — FIX #11.
Run with: pytest tests/test_kill_switch.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.kill_switch import KillSwitch, settings as kill_switch_settings


@pytest.fixture
def ks():
    """Fresh KillSwitch instance for each test."""
    return KillSwitch()


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.get_positions = AsyncMock(return_value=[])
    broker.place_order = AsyncMock(return_value=MagicMock(status="submitted"))
    broker.ib = MagicMock()
    broker.ib.openOrders = MagicMock(return_value=[])
    return broker


@pytest.fixture
def mock_scheduler():
    s = MagicMock()
    s.pause = MagicMock()
    s.resume = MagicMock()
    return s


@pytest.mark.asyncio
async def test_kill_switch_not_engaged_by_default(ks):
    assert ks.is_engaged is False


@pytest.mark.asyncio
async def test_kill_switch_engage_sets_flag(ks, mock_broker, mock_scheduler):
    ks.configure(mock_broker, mock_scheduler)
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()
        ))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        await ks.engage("test")
    assert ks.is_engaged is True


@pytest.mark.asyncio
async def test_kill_switch_pauses_scheduler(ks, mock_broker, mock_scheduler):
    ks.configure(mock_broker, mock_scheduler)
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()
        ))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        await ks.engage("scheduler_test")
    mock_scheduler.pause.assert_called_once()


@pytest.mark.asyncio
async def test_kill_switch_double_engage_is_idempotent(ks, mock_broker, mock_scheduler):
    ks.configure(mock_broker, mock_scheduler)
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()
        ))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        await ks.engage("first")
        result = await ks.engage("second")
    assert result["status"] == "already_engaged"
    assert mock_scheduler.pause.call_count == 1  # only paused once


@pytest.mark.asyncio
async def test_kill_switch_reset_requires_auth_code(ks, monkeypatch):
    monkeypatch.setattr(kill_switch_settings, "kill_switch_reset_code", "test-reset-code")
    ks._engaged = True
    result = await ks.reset("wrong_code")
    assert result["reset"] is False
    assert ks.is_engaged is True


@pytest.mark.asyncio
async def test_kill_switch_reset_with_correct_code(ks, mock_scheduler, monkeypatch):
    monkeypatch.setattr(kill_switch_settings, "kill_switch_reset_code", "test-reset-code")
    ks._engaged = True
    ks._scheduler = mock_scheduler
    result = await ks.reset("test-reset-code")
    assert result["reset"] is True
    assert ks.is_engaged is False
    mock_scheduler.resume.assert_called_once()


@pytest.mark.asyncio
async def test_kill_switch_flattens_open_positions(ks, mock_scheduler):
    from unittest.mock import AsyncMock, MagicMock
    from app.broker.broker_interface import Position
    from datetime import date
    from decimal import Decimal

    mock_pos = Position(
        symbol="SPY240119P00450000", underlying="SPY",
        strike=Decimal("450"), expiration=date(2024, 1, 19),
        option_type="put", quantity=-1, avg_cost=Decimal("1.25"),
    )
    broker = MagicMock()
    broker.get_positions = AsyncMock(return_value=[mock_pos])
    broker.place_order = AsyncMock(return_value=MagicMock(status="submitted"))
    broker.ib = MagicMock()
    broker.ib.openOrders = MagicMock(return_value=[])

    ks.configure(broker, mock_scheduler)
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()
        ))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ks.engage("test_flatten")

    assert result["positions_flattened"] == 1
    broker.place_order.assert_called_once()
