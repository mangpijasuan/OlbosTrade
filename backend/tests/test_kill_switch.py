"""
Kill switch tests — FIX #11.
Run with: pytest tests/test_kill_switch.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.kill_switch import KillSwitch


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
    monkeypatch.setattr(
        "app.core.config.settings.kill_switch_reset_code", "TEST_RESET_CODE"
    )
    ks._engaged = True
    result = await ks.reset("wrong_code")
    assert result["reset"] is False
    assert ks.is_engaged is True


@pytest.mark.asyncio
async def test_kill_switch_reset_disabled_when_unset(ks, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.kill_switch_reset_code", "")
    ks._engaged = True
    result = await ks.reset("anything")
    assert result["reset"] is False
    assert "not configured" in result["reason"].lower()
    assert ks.is_engaged is True


@pytest.mark.asyncio
async def test_kill_switch_reset_with_correct_code(ks, mock_scheduler, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.kill_switch_reset_code", "TEST_RESET_CODE"
    )
    ks._engaged = True
    ks._scheduler = mock_scheduler
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()
        ))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ks.reset("TEST_RESET_CODE")
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


@pytest.mark.asyncio
async def test_kill_switch_option_flatten_uses_root_symbol(ks, mock_scheduler):
    """Option flatten must use the ROOT underlying (SPY), not the OCC localSymbol,
    or contract qualification fails and the position is left naked. Must also be MKT."""
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
    broker.place_equity_order = AsyncMock(return_value=MagicMock(status="submitted"))
    broker.ib = MagicMock()
    broker.ib.openOrders = MagicMock(return_value=[])

    ks.configure(broker, mock_scheduler)
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ks.engage("test_root_symbol")

    assert result["positions_flattened"] == 1
    broker.place_order.assert_called_once()
    submitted_order = broker.place_order.call_args.args[0]
    assert submitted_order.legs[0].symbol == "SPY"          # root, not OCC symbol
    assert submitted_order.legs[0].action == "BUY"          # closing a short put
    assert submitted_order.legs[0].quantity == 1            # abs(-1)
    assert submitted_order.order_type == "MKT"
    broker.place_equity_order.assert_not_called()


@pytest.mark.asyncio
async def test_kill_switch_flattens_equity_via_equity_order(ks, mock_scheduler):
    """Equity positions (strike==0 sentinel) must flatten via place_equity_order,
    NOT through an options combo (which would fail to qualify)."""
    from app.broker.broker_interface import Position
    from datetime import date
    from decimal import Decimal

    equity_pos = Position(
        symbol="AAPL", underlying="AAPL",
        strike=Decimal("0"), expiration=date.today(),
        option_type="call", quantity=10, avg_cost=Decimal("180.00"),
    )
    broker = MagicMock()
    broker.get_positions = AsyncMock(return_value=[equity_pos])
    broker.place_order = AsyncMock(return_value=MagicMock(status="submitted"))
    broker.place_equity_order = AsyncMock(return_value=MagicMock(status="submitted"))
    broker.ib = MagicMock()
    broker.ib.openOrders = MagicMock(return_value=[])

    ks.configure(broker, mock_scheduler)
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ks.engage("test_equity_flatten")

    assert result["positions_flattened"] == 1
    broker.place_order.assert_not_called()                  # no options combo
    broker.place_equity_order.assert_called_once()
    kwargs = broker.place_equity_order.call_args.kwargs
    assert kwargs["ticker"] == "AAPL"
    assert kwargs["side"] == "SELL"                         # closing a long
    assert kwargs["qty"] == 10
    assert kwargs["order_type"] == "market"


@pytest.mark.asyncio
async def test_kill_switch_reports_rejected_flatten_as_error(ks, mock_scheduler):
    """A broker-rejected flatten must NOT be counted as flattened — it is an error
    requiring manual intervention (naked position remains)."""
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
    broker.place_order = AsyncMock(return_value=MagicMock(status="rejected", message="no route"))
    broker.ib = MagicMock()
    broker.ib.openOrders = MagicMock(return_value=[])

    ks.configure(broker, mock_scheduler)
    with patch("app.services.kill_switch.AsyncSessionLocal") as mock_db:
        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            add=MagicMock(), commit=AsyncMock()))
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ks.engage("test_rejected_flatten")

    assert result["positions_flattened"] == 0
    assert any("flatten_" in e for e in result["errors"])
