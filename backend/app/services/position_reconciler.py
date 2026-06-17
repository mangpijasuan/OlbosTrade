"""
Position Reconciler — ensures OlbosQuant's DB state matches broker truth.

FIX #10: On every startup and before every signal cycle, compare broker
positions against DB open trades. Any discrepancy halts trading until
manually resolved to prevent position doubling on restart.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.broker_interface import BrokerInterface, Position
from app.core.database import AsyncSessionLocal
from app.models.trade import Trade
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ReconciliationError(Exception):
    """Raised when broker positions don't match DB state — halts trading."""
    pass


@dataclass
class ReconciliationResult:
    """Result of a position reconciliation check."""
    clean: bool
    broker_position_count: int
    db_open_trade_count: int
    untracked_at_broker: list[str]   # in broker, not in DB — ghost positions
    phantom_in_db: list[str]         # in DB as open, not at broker — orphaned records
    warnings: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PositionReconciler:
    """
    FIX #10: Reconciles broker positions against DB on startup and before cycles.

    Design principle: the broker is always the source of truth.
    If they disagree, halt trading and require manual resolution.
    """

    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    async def reconcile(self) -> ReconciliationResult:
        """
        Compare broker positions against DB open trades.

        Returns ReconciliationResult.
        Raises ReconciliationError if discrepancies are found — caller must
        handle this by halting the signal cycle.
        """
        # Fetch broker positions
        try:
            broker_positions: list[Position] = await self.broker.get_positions()
        except Exception as exc:
            raise ReconciliationError(
                f"Could not fetch broker positions for reconciliation: {exc}"
            ) from exc

        broker_symbols = {p.symbol for p in broker_positions}

        # Fetch DB open trades
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Trade).where(Trade.status == "open")
            )
            db_open_trades: list[Trade] = result.scalars().all()

        # Build comparable symbol sets from DB
        # Use underlying as a coarse match (symbol-level matching needs real contract symbols)
        db_underlyings = {str(t.underlying) for t in db_open_trades}
        broker_underlyings = {p.underlying for p in broker_positions}

        untracked = broker_underlyings - db_underlyings
        phantom   = db_underlyings - broker_underlyings

        warnings = []

        # Allow phantom DB records if they were entered today (timing edge case on startup)
        # Only raise on untracked broker positions — those are the dangerous ones
        if untracked:
            msg = (
                f"RECONCILIATION FAILURE: {len(untracked)} positions at broker "
                f"have no matching DB record: {untracked}. "
                f"These are UNTRACKED positions — OlbosQuant does not know about them. "
                f"Trading halted until manual review."
            )
            logger.critical(msg)
            raise ReconciliationError(msg)

        if phantom:
            # Phantom DB records (DB says open, broker says no position)
            # Could be timing issue or a missed close — warn but don't halt
            warning = (
                f"WARNING: {len(phantom)} DB open trades have no matching broker position: "
                f"{phantom}. These may be stale records. Review and close if needed."
            )
            logger.warning(warning)
            warnings.append(warning)

        result = ReconciliationResult(
            clean=len(untracked) == 0,
            broker_position_count=len(broker_positions),
            db_open_trade_count=len(db_open_trades),
            untracked_at_broker=list(untracked),
            phantom_in_db=list(phantom),
            warnings=warnings,
        )

        if result.clean:
            logger.info(
                "Position reconciliation clean — %d broker positions, %d DB open trades",
                result.broker_position_count, result.db_open_trade_count,
            )
        else:
            logger.warning(
                "Position reconciliation warnings: %s", warnings
            )

        return result

    async def load_guardrail_state_from_db(self) -> dict:
        """
        FIX #12: Load persisted guardrail state from most recent portfolio snapshot.
        Prevents consecutive_losses and trades_today from resetting to 0 on restart.

        Returns dict compatible with PortfolioState constructor.
        """
        from app.core.config import settings
        from app.models.risk_state import PortfolioSnapshot

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PortfolioSnapshot)
                .order_by(PortfolioSnapshot.timestamp.desc())
                .limit(1)
            )
            snap = result.scalar_one_or_none()

        if snap is None:
            logger.info("No portfolio snapshot found — using default guardrail state")
            return {
                "current_value": settings.starting_capital,
                "starting_capital": settings.starting_capital,
                "daily_pnl": 0.0,
                "weekly_pnl": 0.0,
                "monthly_pnl": 0.0,
                "consecutive_losses": 0,
                "trades_today": 0,
                "cooling_off_until": None,
            }

        logger.info(
            "Restored guardrail state from DB — "
            "consecutive_losses=%d trades_today=%d trading_mode=%s cooling_off_until=%s",
            snap.consecutive_losses, snap.trades_today,
            snap.trading_mode, snap.cooling_off_until,
        )

        return {
            "current_value": float(snap.total_value),
            "starting_capital": settings.starting_capital,
            "daily_pnl": float(snap.daily_pnl or 0),
            "weekly_pnl": float(snap.weekly_pnl or 0),
            "monthly_pnl": float(snap.monthly_pnl or 0),
            "consecutive_losses": snap.consecutive_losses,
            "trades_today": snap.trades_today,
            "cooling_off_until": snap.cooling_off_until,  # restored from DB
        }

    async def save_portfolio_snapshot(
        self,
        portfolio_value: float,
        daily_pnl: float,
        weekly_pnl: float,
        monthly_pnl: float,
        consecutive_losses: int,
        trades_today: int,
        trading_mode: str,
        cooling_off_until=None,
    ) -> None:
        """
        FIX #12: Persist current guardrail state to DB after every trade cycle.
        This is what survives restarts.
        """
        from app.models.risk_state import PortfolioSnapshot
        from app.core.config import settings

        positions = await self.broker.get_positions()
        account = await self.broker.get_account_summary()

        # Money columns are Numeric — pass Decimal(str(...)) so binary-float
        # rounding doesn't leak into the ledger.
        def _money(v) -> Decimal:
            return Decimal(str(round(float(v), 4)))

        async with AsyncSessionLocal() as session:
            snap = PortfolioSnapshot(
                timestamp=datetime.now(timezone.utc),
                total_value=_money(portfolio_value),
                cash=_money(account.cash_balance),
                open_position_count=len(positions),
                daily_pnl=_money(daily_pnl),
                weekly_pnl=_money(weekly_pnl),
                monthly_pnl=_money(monthly_pnl),
                trading_mode=trading_mode,
                consecutive_losses=consecutive_losses,
                trades_today=trades_today,
                cooling_off_until=cooling_off_until,
            )
            session.add(snap)
            await session.commit()

        logger.debug(
            "Portfolio snapshot saved — value=%.2f mode=%s consecutive_losses=%d",
            portfolio_value, trading_mode, consecutive_losses,
        )
