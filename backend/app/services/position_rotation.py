"""
Position rotation — free slots when at max concurrent opens.

When a new equity entry is blocked by max_positions and
``settings.position_rotation_on_max`` is True, close N open equity
positions so the new trade can proceed. Winner Protection is a hard floor,
not a ranking preference: a position with unrealized P&L above
``settings.position_rotation_winner_pnl_floor`` (default: any profit at
all) is never a rotation target, full stop — it is excluded before any
ranking happens, and if too few non-winners remain to free the requested
slots, rotation is skipped entirely rather than touching a winner.

Among the eligible (non-winning) positions, closure order is:

  1. Lowest Position Quality Score (``compute_equity_hold_score`` —
     alpha_edge_engine.py's hold-score reused, not a new formula)
  2. Lowest entry ``signal_score`` among ties / missing quality score
  3. Oldest ``entry_date`` among ties / missing both

Never closes the incoming ticker's underlying. Equity only (v1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RotationCandidate:
    trade_id: str
    underlying: str
    unrealized_pnl: float
    confidence: Optional[float]
    entry_date: Optional[datetime]
    spread_type: str
    quality_score: Optional[float] = None


def _rank_key(c: RotationCandidate):
    """Ascending sort key: quality_score (None-last) -> confidence
    (None-last) -> oldest entry_date. Tuple-of-tuples so a missing field
    always sorts after every real value at that tier, never interpolated
    as if it were a real score."""
    quality = (0, c.quality_score) if c.quality_score is not None else (1, 0.0)
    confidence = (0, c.confidence) if c.confidence is not None else (1, 0.0)
    entry = c.entry_date or datetime.min.replace(tzinfo=timezone.utc)
    return (quality, confidence, entry)


def select_rotation_targets(
    candidates: Sequence[RotationCandidate],
    *,
    incoming_ticker: str,
    count: int = 2,
) -> list[RotationCandidate]:
    """
    Pick up to ``count`` equity positions to close for a new entry.

    Returns [] if fewer than ``count`` eligible candidates remain after
    excluding the incoming underlying and applying the Winner Protection
    floor (caller should keep blocking rather than touch a winner).
    """
    if count <= 0:
        return []
    incoming = (incoming_ticker or "").upper()
    pool = [
        c for c in candidates
        if (c.underlying or "").upper() != incoming
        and (c.spread_type or "").lower() in ("equity_long", "equity_short")
    ]

    winner_floor = float(getattr(settings, "position_rotation_winner_pnl_floor", 0.0) or 0.0)
    eligible = [c for c in pool if c.unrealized_pnl <= winner_floor]
    if len(eligible) < count:
        return []

    return sorted(eligible, key=_rank_key)[:count]


def _equity_entry_price(trade: Any) -> float:
    return float(getattr(trade, "credit_received", None) or 0)


def _equity_unrealized(trade: Any, mid: float) -> float:
    entry = _equity_entry_price(trade)
    qty = int(getattr(trade, "quantity", None) or 1)
    st = (getattr(trade, "spread_type", None) or "").lower()
    if entry <= 0 or mid <= 0:
        return 0.0
    if st == "equity_short":
        return (entry - mid) * qty
    return (mid - entry) * qty


async def _mid_price(broker: Any, ticker: str) -> Optional[float]:
    try:
        from app.broker.ibkr_coordinator import Priority, ibkr_coordinator
        quote = await ibkr_coordinator.submit(
            Priority.P1,
            lambda: broker.get_latest_quote(ticker),
            req_type="QUOTE",
            symbol=ticker,
            timeout=30.0,
        )
        bid = float(getattr(quote, "bid_price", 0) or 0)
        ask = float(getattr(quote, "ask_price", 0) or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        last = float(getattr(quote, "last_price", 0) or 0)
        return last if last > 0 else None
    except Exception as exc:
        logger.warning("rotation quote failed for %s: %s", ticker, exc)
        return None


async def close_equity_trade(
    trade: Any,
    *,
    broker: Any,
    closed_by: str = "position_rotation",
    order_type: str = "market",
    limit_price: Optional[float] = None,
) -> dict:
    """
    Submit an equity close for an open Trade row. Shared by manual close and rotation.
    Does not check kill switch (closing reduces risk).
    """
    from app.broker.ibkr_coordinator import Priority, ibkr_coordinator
    from app.services.trade_recorder import trade_recorder

    spread_type = (getattr(trade, "spread_type", None) or "").lower()
    if spread_type not in ("equity_long", "equity_short"):
        raise ValueError(f"equity close only; got spread_type={spread_type!r}")

    close_side = "SELL" if spread_type == "equity_long" else "BUY"
    ticker = trade.underlying
    qty = int(trade.quantity or 1)
    trade_id = str(trade.id)

    cancelled = await broker.cancel_open_orders(ticker)
    result = await ibkr_coordinator.submit(
        Priority.P0,
        lambda: broker.place_equity_order(
            ticker=ticker, qty=qty, side=close_side,
            order_type=order_type, limit_price=limit_price,
        ),
        req_type="PLACE_ORDER", symbol=ticker,
    )
    if result.status in ("cancelled", "rejected"):
        raise RuntimeError(f"broker rejected close for {ticker}: {result.status}")

    if result.status == "filled" and result.fill_price is not None:
        await trade_recorder.record_exit(
            trade_id=trade_id,
            cost_to_close=float(result.fill_price),
            exit_reason="position_rotation" if closed_by == "position_rotation" else "manual",
        )

    return {
        "trade_id": trade_id,
        "ticker": ticker,
        "action": close_side,
        "quantity": qty,
        "order_id": result.order_id,
        "status": result.status,
        "cancelled_open_orders": cancelled,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "closed_by": closed_by,
    }


async def rotate_for_new_equity_entry(
    *,
    incoming_ticker: str,
    broker: Any,
    log_execution=None,
) -> list[dict]:
    """
    Close configured number of equity positions to free a slot.

    Returns list of close receipts (may be empty if rotation not possible).
    """
    if not getattr(settings, "position_rotation_on_max", False):
        return []

    n = max(int(getattr(settings, "position_rotation_closes", 2) or 2), 1)
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        open_trades = (
            await session.execute(select(Trade).where(Trade.status == "open"))
        ).scalars().all()

    equity_opens = [
        t for t in open_trades
        if (t.spread_type or "").lower() in ("equity_long", "equity_short")
    ]
    if len(equity_opens) < n:
        logger.info(
            "rotation skipped — need %d equity opens, have %d",
            n, len(equity_opens),
        )
        return []

    from app.services.alpha_edge_engine import compute_equity_hold_score

    candidates: list[RotationCandidate] = []
    for t in equity_opens:
        mid = await _mid_price(broker, t.underlying)
        # No quote → treat unrealized as 0 so we don't invent P&L
        upnl = _equity_unrealized(t, mid) if mid is not None else 0.0
        conf = float(t.signal_score) if t.signal_score is not None else None
        direction = "BUY" if (t.spread_type or "").lower() == "equity_long" else "SELL"
        try:
            quality = await compute_equity_hold_score(t.underlying, direction)
        except Exception as exc:
            logger.warning("rotation quality score failed for %s: %s", t.underlying, exc)
            quality = None
        candidates.append(
            RotationCandidate(
                trade_id=str(t.id),
                underlying=t.underlying,
                unrealized_pnl=upnl,
                confidence=conf,
                entry_date=t.entry_date,
                spread_type=t.spread_type or "",
                quality_score=quality,
            )
        )

    targets = select_rotation_targets(
        candidates, incoming_ticker=incoming_ticker, count=n,
    )
    if len(targets) < n:
        logger.info(
            "rotation skipped — fewer than %d eligible targets (incoming=%s)",
            n, incoming_ticker,
        )
        return []

    by_id = {str(t.id): t for t in equity_opens}
    receipts: list[dict] = []
    for target in targets:
        trade = by_id.get(target.trade_id)
        if trade is None:
            continue
        try:
            receipt = await close_equity_trade(
                trade, broker=broker, closed_by="position_rotation",
            )
            receipts.append(receipt)
            if log_execution is not None:
                await log_execution(receipt)
            logger.info(
                "rotation closed %s trade_id=%s unrealized≈%.2f quality=%s confidence=%s",
                target.underlying, target.trade_id,
                target.unrealized_pnl, target.quality_score, target.confidence,
            )
        except Exception as exc:
            logger.error(
                "rotation close failed for %s (%s): %s",
                target.underlying, target.trade_id, exc,
            )
            # Partial closes still help free slots; continue
            continue

    return receipts
