"""
Trade excursion tracker.

Updates open trades with live MFE / MAE using normalized broker position
unrealized P&L. This creates useful post-trade learning metrics without
requiring a full event-sourced position engine yet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select

from app.broker.broker_interface import Position
from app.core.database import AsyncSessionLocal
from app.models.trade import Trade
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExcursionUpdateResult:
    updated_trades: int = 0
    skipped_missing_marks: int = 0
    skipped_ambiguous_underlyings: list[str] = field(default_factory=list)


class TradeExcursionTracker:
    """
    Best-effort excursion tracker based on current broker marks.

    Matching is intentionally conservative:
    - positions are grouped by underlying
    - trades are grouped by underlying
    - if more than one open trade shares the same underlying, we skip it
      rather than write misleading MFE / MAE
    """

    async def update_from_broker_positions(
        self,
        broker_positions: list[Position],
    ) -> ExcursionUpdateResult:
        marks_by_underlying: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        missing_marks = 0

        for position in broker_positions:
            key = self._position_key(position)
            if not key:
                continue
            pnl = self._position_unrealized_pnl(position)
            if pnl is None:
                missing_marks += 1
                continue
            marks_by_underlying[key] += pnl

        result = ExcursionUpdateResult(skipped_missing_marks=missing_marks)

        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                select(Trade).where(Trade.status == "open")
            )
            open_trades: list[Trade] = rows.scalars().all()

            trades_by_underlying: dict[str, list[Trade]] = defaultdict(list)
            for trade in open_trades:
                key = self._trade_key(trade)
                if key:
                    trades_by_underlying[key].append(trade)

            for underlying, current_pnl in marks_by_underlying.items():
                trades = trades_by_underlying.get(underlying, [])
                if len(trades) != 1:
                    if len(trades) > 1:
                        result.skipped_ambiguous_underlyings.append(underlying)
                    continue

                trade = trades[0]
                previous_mfe = self._as_decimal(trade.mfe_pnl)
                previous_mae = self._as_decimal(trade.mae_pnl)

                next_mfe = max(previous_mfe, current_pnl, Decimal("0"))
                next_mae = min(previous_mae, current_pnl, Decimal("0"))

                if next_mfe != previous_mfe or next_mae != previous_mae:
                    trade.mfe_pnl = next_mfe
                    trade.mae_pnl = next_mae
                    result.updated_trades += 1

            if result.updated_trades > 0:
                await session.commit()

        if result.skipped_ambiguous_underlyings:
            logger.warning(
                "Trade excursion tracker skipped ambiguous underlyings: %s",
                result.skipped_ambiguous_underlyings,
            )

        return result

    @staticmethod
    def _trade_key(trade: Trade) -> str:
        return str(getattr(trade, "underlying", "") or "").upper()

    @staticmethod
    def _position_key(position: Position) -> str:
        return str(getattr(position, "underlying", "") or getattr(position, "symbol", "") or "").upper()

    @staticmethod
    def _as_decimal(value) -> Decimal:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

    def _position_unrealized_pnl(self, position: Position) -> Decimal | None:
        current = getattr(position, "unrealized_pnl", None)
        if current is not None:
            return self._as_decimal(current)

        current_price = getattr(position, "current_price", None)
        avg_cost = getattr(position, "avg_cost", None)
        quantity = getattr(position, "quantity", None)
        if current_price is None or avg_cost is None or quantity is None:
            return None

        return (
            self._as_decimal(current_price) - self._as_decimal(avg_cost)
        ) * Decimal(str(quantity))


trade_excursion_tracker = TradeExcursionTracker()
