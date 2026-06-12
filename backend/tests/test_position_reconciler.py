"""
Position reconciler tests — FIX #10.
Run with: pytest tests/test_position_reconciler.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date
from decimal import Decimal

from app.broker.broker_interface import Position
from app.services.position_reconciler import PositionReconciler, ReconciliationError


def make_position(symbol: str, underlying: str, qty: int = -1) -> Position:
    return Position(
        symbol=symbol, underlying=underlying,
        strike=Decimal("450"), expiration=date(2024, 1, 19),
        option_type="put", quantity=qty, avg_cost=Decimal("1.25"),
    )


@pytest.fixture
def mock_broker():
    b = MagicMock()
    b.get_positions = AsyncMock(return_value=[])
    return b


@pytest.mark.asyncio
async def test_reconcile_clean_no_positions(mock_broker):
    """No broker positions + no DB trades = clean."""
    reconciler = PositionReconciler(mock_broker)
    with patch("app.services.position_reconciler.AsyncSessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await reconciler.reconcile()
    assert result.clean is True
    assert result.broker_position_count == 0
    assert result.db_open_trade_count == 0


@pytest.mark.asyncio
async def test_reconcile_untracked_broker_position_raises(mock_broker):
    """Broker has a position OlbosQuant doesn't know about — must raise."""
    mock_broker.get_positions = AsyncMock(
        return_value=[make_position("SPY240119P00450000", "SPY")]
    )
    reconciler = PositionReconciler(mock_broker)
    with patch("app.services.position_reconciler.AsyncSessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(ReconciliationError, match="UNTRACKED"):
            await reconciler.reconcile()


@pytest.mark.asyncio
async def test_reconcile_phantom_db_trade_warns_not_raises(mock_broker):
    """DB has open trade but broker has no position — warn, don't halt."""
    mock_broker.get_positions = AsyncMock(return_value=[])
    reconciler = PositionReconciler(mock_broker)

    mock_trade = MagicMock()
    mock_trade.underlying = "SPY"

    with patch("app.services.position_reconciler.AsyncSessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_trade])))
        ))
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await reconciler.reconcile()

    assert result.clean is True  # phantom doesn't fail clean check
    assert len(result.phantom_in_db) == 1
    assert len(result.warnings) == 1


@pytest.mark.asyncio
async def test_reconcile_matching_positions_is_clean(mock_broker):
    """Broker and DB agree on SPY position — clean."""
    mock_broker.get_positions = AsyncMock(
        return_value=[make_position("SPY240119P00450000", "SPY")]
    )
    reconciler = PositionReconciler(mock_broker)

    mock_trade = MagicMock()
    mock_trade.underlying = "SPY"

    with patch("app.services.position_reconciler.AsyncSessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_trade])))
        ))
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await reconciler.reconcile()

    assert result.clean is True
    assert len(result.untracked_at_broker) == 0
