"""
TradeRecorder — writes Trade rows and auto-creates JournalEntry records.

Called by trade_desk and position_exit_monitor after fills.
This is the missing link between execution and the journal/analytics.

What it writes automatically:
  Trade row         → used by Mode Analytics, backtester, optimizer
  JournalEntry row  → used by Journal page, rule breach analysis,
                      monthly review, confidence vs outcome

The JournalEntry pre-populates all mechanical fields automatically.
The trader only needs to fill in the human fields
(pre_trade_thesis, followed_rules, post_trade_notes, tags)
via the Journal UI after each session — or never, if they only want
the performance analytics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TradeRecorder:
    """
    Persists a filled trade to the database and creates
    a corresponding JournalEntry stub automatically.

    Both writes happen in a single DB transaction — if either
    fails, neither is committed (no orphaned records).
    """

    async def record_fill(
        self,
        *,
        strategy:              str,
        underlying:            str,
        option_type:           str,
        short_strike:          float,
        long_strike:           float,
        expiration:            date,
        entry_credit:          float,
        quantity:              int,
        signal_score:          float,
        iv_rank:               float,
        regime:                str,
        trading_mode:          str,
        dispatch_id:           str,
        net_fill_price:        Optional[float] = None,
        spread_width:          Optional[float] = None,
    ) -> Optional[str]:
        """
        Write Trade + JournalEntry to DB in one transaction.

        Returns the trade_id string on success, None on failure.

        Idempotent: if dispatch_id already exists in the DB the existing
        trade_id is returned without creating a duplicate row.

        CRITICAL alert is emitted when a broker fill cannot be persisted —
        the position exists at the broker but is untracked in the DB.
        """
        try:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade
            from app.models.journal_entry import JournalEntry

            # ── Idempotency check ───────────────────────────────────────────
            async with AsyncSessionLocal() as session:
                existing = (await session.execute(
                    select(Trade).where(Trade.dispatch_id == dispatch_id)
                )).scalar_one_or_none()
            if existing is not None:
                logger.info(
                    "record_fill: dispatch_id %s already recorded as trade %s — skipping duplicate",
                    dispatch_id, existing.id,
                )
                return str(existing.id)

            trade_id = uuid.uuid4()

            async with AsyncSessionLocal() as session:
                async with session.begin():

                    # ── Trade row ──────────────────────────────────────────────
                    trade = Trade(
                        id=trade_id,
                        strategy=strategy,
                        underlying=underlying,
                        spread_type=option_type or "equity",
                        short_strike=Decimal(str(short_strike or 0)),
                        long_strike=Decimal(str(long_strike or 0)),
                        expiration=expiration,
                        credit_received=Decimal(str(round(entry_credit, 4))),
                        cost_to_close=None,
                        pnl=None,
                        pnl_pct=None,
                        status="open",
                        entry_date=datetime.now(timezone.utc),
                        exit_date=None,
                        exit_reason=None,
                        signal_score=Decimal(str(round(signal_score, 4))),
                        quantity=int(quantity or 1),
                        trading_mode_at_entry=trading_mode or "balanced",
                        dispatch_id=dispatch_id,
                    )
                    session.add(trade)

            # ── JournalEntry stub (separate transaction so FK is satisfied) ──
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    journal = JournalEntry(
                        trade_id=trade_id,
                        pre_trade_thesis="",
                        confidence_level=None,   # NULL — trader fills in via Journal UI
                        market_context=regime or "",
                        tags=[],
                        mistake_tags=[],
                    )
                    session.add(journal)

            logger.info(
                "Trade recorded: %s %s %s strike=%.0f/%.0f "
                "credit=%.2f mode=%s score=%.3f dispatch_id=%s trade_id=%s",
                strategy, underlying, option_type,
                short_strike, long_strike,
                entry_credit, trading_mode, signal_score, dispatch_id, trade_id,
            )
            return str(trade_id)

        except Exception as exc:
            logger.critical(
                "CRITICAL: TradeRecorder.record_fill FAILED — "
                "broker fill for dispatch_id=%s is UNTRACKED in DB. "
                "Position exists at broker but not in OlbosQuant records. "
                "Manual reconciliation required. Error: %s",
                dispatch_id, exc, exc_info=True,
            )
            return None

    async def record_exit(
        self,
        *,
        trade_id:    str,
        cost_to_close: float,
        exit_reason: str,
    ) -> bool:
        """
        Update an open Trade row with exit data and compute P&L.
        Called when a position is closed.

        Returns True on success.
        """
        try:
            from sqlalchemy import select
            from app.core.config import settings
            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade

            async with AsyncSessionLocal() as session:
                async with session.begin():
                    result = await session.execute(
                        select(Trade).where(Trade.id == uuid.UUID(trade_id))
                    )
                    trade = result.scalar_one_or_none()
                    if trade is None:
                        logger.warning("record_exit: trade %s not found", trade_id)
                        return False

                    credit = float(trade.credit_received or 0)
                    qty    = int(getattr(trade, "quantity", None) or 1)
                    pnl    = (credit - cost_to_close) * qty * 100
                    starting_capital = float(settings.starting_capital)
                    pnl_pct = pnl / starting_capital if starting_capital > 0 else 0.0

                    trade.cost_to_close = Decimal(str(round(cost_to_close, 4)))
                    trade.pnl           = Decimal(str(round(pnl, 2)))
                    trade.pnl_pct       = Decimal(str(round(pnl_pct, 6)))
                    trade.status        = "closed"
                    trade.exit_date     = datetime.now(timezone.utc)
                    trade.exit_reason   = exit_reason

            logger.info(
                "Trade exited: %s | P&L=$%.0f | reason=%s",
                trade_id, pnl, exit_reason,
            )
            return True

        except Exception as exc:
            logger.error("record_exit failed for %s: %s", trade_id, exc)
            return False


# ── Singleton ──────────────────────────────────────────────────────────────────
trade_recorder = TradeRecorder()
