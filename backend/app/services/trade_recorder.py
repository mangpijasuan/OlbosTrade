"""
TradeRecorder — writes Trade rows and auto-creates JournalEntry records.

Called by paper_trader.py immediately after a successful fill.
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
        Never raises — logs errors and returns None so the signal
        cycle is never blocked by a DB write failure.
        """
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade
            from app.models.journal_entry import JournalEntry
            from sqlalchemy import select
            from sqlalchemy.exc import IntegrityError

            # Normalise the dispatch id: empty/whitespace → None so multiple
            # rows without a real broker order id don't collide on the UNIQUE
            # index (NULLs are distinct).
            dispatch_key = (dispatch_id or "").strip() or None

            trade_id = uuid.uuid4()

            # Both rows are written in ONE transaction. flush() inserts the
            # Trade first so the JournalEntry FK is satisfied; if the journal
            # insert fails, the trade is rolled back too — no orphaned trade
            # with no journal (which previously made callers see None and retry,
            # duplicating the position).
            async with AsyncSessionLocal() as session:
                # Idempotency: if this fill was already recorded (e.g. a retry
                # or a second close path after a restart, where the in-process
                # guard is gone), return the existing trade_id instead of
                # inserting a duplicate position.
                if dispatch_key is not None:
                    existing = await session.execute(
                        select(Trade.id).where(Trade.dispatch_id == dispatch_key)
                    )
                    prior = existing.scalar_one_or_none()
                    if prior is not None:
                        logger.warning(
                            "record_fill: dispatch_id %s already recorded as trade %s "
                            "— skipping duplicate", dispatch_key, prior,
                        )
                        return str(prior)

                try:
                    async with session.begin():
                        is_equity = (option_type or "").lower() == "equity"
                        trade = Trade(
                            id=trade_id,
                            strategy=strategy,
                            underlying=underlying,
                            dispatch_id=dispatch_key,
                            # instrument_type was never set on write, so every row
                            # stayed the "option" server-default — which made
                            # record_exit apply the ×100 options multiplier to equity
                            # P&L. Set it explicitly from the leg type.
                            instrument_type="equity" if is_equity else "option",
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
                        )
                        session.add(trade)
                        await session.flush()  # insert Trade so the FK below resolves

                        journal = JournalEntry(
                            trade_id=trade_id,
                            pre_trade_thesis="",
                            confidence_level=3,
                            market_context=regime or "",
                            tags=[],
                            mistake_tags=[],
                        )
                        session.add(journal)
                except IntegrityError:
                    # Lost a race on the UNIQUE dispatch_id — another path
                    # recorded the same fill first. Return that row, not a dup.
                    await session.rollback()
                    if dispatch_key is not None:
                        again = await session.execute(
                            select(Trade.id).where(Trade.dispatch_id == dispatch_key)
                        )
                        prior = again.scalar_one_or_none()
                        if prior is not None:
                            logger.warning(
                                "record_fill: dispatch_id %s recorded concurrently as "
                                "trade %s — skipping duplicate", dispatch_key, prior,
                            )
                            return str(prior)
                    raise

            logger.info(
                "Trade recorded: %s %s %s strike=%.0f/%.0f "
                "credit=%.2f mode=%s score=%.3f trade_id=%s",
                strategy, underlying, option_type,
                short_strike, long_strike,
                entry_credit, trading_mode, signal_score, trade_id,
            )
            return str(trade_id)

        except Exception as exc:
            logger.error(
                "TradeRecorder.record_fill failed — "
                "trade NOT persisted: %s", exc, exc_info=True,
            )
            return None

    @staticmethod
    def _gross_pnl(
        *, credit: float, cost_to_close: float, qty: int,
        is_equity: bool, strategy: str,
    ) -> float:
        """
        Gross P&L (before commission) for a closing trade.

        - Equity: no ×100 contract multiplier. Entry price is stored in
          credit_received, exit price in cost_to_close, so a LONG position's
          P&L is (exit − entry) × shares = (cost_to_close − credit) × qty.
          NOTE: assumes LONG — short-equity P&L is the inverse, which needs a
          stored side (not yet modeled).
        - Debit spread: pays a debit at entry, receives value at exit, so the
          sign is the inverse of a credit spread.
        - Credit spread (default): (credit − cost_to_close) × qty × 100.
        """
        if is_equity:
            return (cost_to_close - credit) * qty
        if "debit" in (strategy or "").lower():
            return (cost_to_close - credit) * qty * 100
        return (credit - cost_to_close) * qty * 100

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
            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade
            from sqlalchemy import select, update

            async with AsyncSessionLocal() as session:
                async with session.begin():
                    # Lock the row and only match if still open — prevents two
                    # concurrent close paths (e.g. profit-target watcher + manual
                    # close) from both applying the exit and double-counting P&L.
                    result = await session.execute(
                        select(Trade)
                        .where(Trade.id == uuid.UUID(trade_id), Trade.status == "open")
                        .with_for_update()
                    )
                    trade = result.scalar_one_or_none()
                    if trade is None:
                        logger.warning(
                            "record_exit: trade %s not found or already closed", trade_id
                        )
                        return False

                    from app.core.config import settings

                    credit     = float(trade.credit_received or 0)
                    qty        = int(getattr(trade, "quantity", None) or 1)
                    commission = float(getattr(trade, "commission_paid", None) or 0)

                    is_equity = (
                        (getattr(trade, "instrument_type", "") or "").lower() == "equity"
                        or (trade.spread_type or "").lower() == "equity"
                    )
                    gross = self._gross_pnl(
                        credit=credit, cost_to_close=cost_to_close, qty=qty,
                        is_equity=is_equity, strategy=trade.strategy or "",
                    )
                    pnl = gross - commission
                    pnl_pct = pnl / float(settings.starting_capital or 25000)

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
