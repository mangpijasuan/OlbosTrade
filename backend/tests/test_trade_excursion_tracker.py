from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker.broker_interface import Position
from app.services.trade_excursion_tracker import TradeExcursionTracker


def make_position(underlying: str, unrealized_pnl: str) -> Position:
    return Position(
        symbol=f"{underlying}240119P00450000",
        underlying=underlying,
        strike=Decimal("450"),
        expiration=date(2024, 1, 19),
        option_type="put",
        quantity=-1,
        avg_cost=Decimal("1.25"),
        unrealized_pnl=Decimal(unrealized_pnl),
    )


def _db_result_with_trades(trades):
    return MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=trades)))
    )


@pytest.mark.asyncio
async def test_excursion_tracker_updates_mfe_and_mae():
    tracker = TradeExcursionTracker()

    trade = MagicMock()
    trade.underlying = "SPY"
    trade.status = "open"
    trade.mfe_pnl = Decimal("80")
    trade.mae_pnl = Decimal("-15")

    with patch("app.services.trade_excursion_tracker.AsyncSessionLocal") as mock_db:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_db_result_with_trades([trade]))
        session.commit = AsyncMock()
        mock_db.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tracker.update_from_broker_positions([make_position("SPY", "125.50")])

    assert result.updated_trades == 1
    assert trade.mfe_pnl == Decimal("125.50")
    assert trade.mae_pnl == Decimal("-15")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_excursion_tracker_skips_ambiguous_underlying():
    tracker = TradeExcursionTracker()

    trade_a = MagicMock()
    trade_a.underlying = "SPY"
    trade_a.status = "open"
    trade_a.mfe_pnl = Decimal("0")
    trade_a.mae_pnl = Decimal("0")

    trade_b = MagicMock()
    trade_b.underlying = "SPY"
    trade_b.status = "open"
    trade_b.mfe_pnl = Decimal("0")
    trade_b.mae_pnl = Decimal("0")

    with patch("app.services.trade_excursion_tracker.AsyncSessionLocal") as mock_db:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_db_result_with_trades([trade_a, trade_b]))
        session.commit = AsyncMock()
        mock_db.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tracker.update_from_broker_positions([make_position("SPY", "-45")])

    assert result.updated_trades == 0
    assert result.skipped_ambiguous_underlyings == ["SPY"]
    session.commit.assert_not_awaited()
