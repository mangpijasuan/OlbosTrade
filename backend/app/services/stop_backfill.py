"""
Backfill missing equity stops from the broker's live protective orders.

Positions adopted by the reconciler (main.py::_adopt_untracked_positions) have
no recorded stop — that path writes the live avg_cost into entry, short_strike
and long_strike alike as discovery-time placeholders, because a reconciliation
mismatch carries no entry plan to copy one from. The broker usually *does* hold
a protective stop for those positions; it simply never reached the Trade row.

That gap is why portfolio heat still overstates: position_risk_dollars() falls
back to full notional for any position whose stop it cannot trust, and on
2026-08-29 two of three open positions were in exactly that state.

This module closes the gap by reading the stop back off the live order book.
It writes one column on one kind of row and submits no orders.

Correctness rules, all of them fail-closed:

  - **Refreshed reads only.** A cache fall-back cannot prove what the broker
    is actually holding, and this writes a number the risk gates then trust.
  - **Never overwrite a stop we already believe.** Only rows where
    equity_stop_distance() returns None are candidates. A row carrying a real
    stop from its own entry plan keeps it; this is a backfill, not a
    reconciliation of live orders against recorded intent.
  - **Full coverage or nothing.** The protective orders' remaining quantity
    must equal the broker's live position quantity exactly. Partial coverage
    means part of the position has no stop and therefore unbounded risk;
    blending a stop across it would understate that to zero. Such a row is
    left reporting notional, which is the honest answer.
  - **The broker's quantity, not the DB's.** DB quantity drift is documented
    and has produced real oversold positions; the live position is the truth.
  - **Direction must agree.** A long is protected by a SELL stop below entry,
    a short by a BUY stop above it. Anything else means the orders are not
    what this read assumes, and the row is skipped.

Where several stop tranches cover one position, the recorded stop is their
quantity-weighted average. That is the single scalar which reproduces the
position's true dollar risk exactly: LITE's three tranches (23 @ 709.14,
23 @ 709.96, 22 @ 761.40) blend to 726.33, and 68 x (887.22 - 726.33) is the
same $10,940.86 the tranches add up to individually.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from app.services.portfolio_engine import equity_stop_distance
from app.utils.logger import get_logger

logger = get_logger(__name__)

# A blended stop this close to entry is not a stop — it is the same
# placeholder shape equity_stop_distance() already refuses to believe, and
# writing it would swap one wrong number for another.
MIN_STOP_DISTANCE_FRACTION = 0.001

# Tranche quantities are floats off the wire; tolerate representation noise
# without tolerating a genuinely uncovered share.
QUANTITY_TOLERANCE = 0.01


def _weighted_stop(orders: list[dict]) -> tuple[Optional[float], float]:
    """Quantity-weighted stop across tranches, and the quantity it covers."""
    total_qty = 0.0
    weighted = 0.0
    for o in orders:
        qty = float(o.get("remaining") or 0)
        px = float(o.get("stop_price") or 0)
        if qty <= 0 or px <= 0:
            continue
        total_qty += qty
        weighted += qty * px
    if total_qty <= 0:
        return None, 0.0
    return weighted / total_qty, total_qty


async def backfill_equity_stops(broker: Any, *, dry_run: bool = True) -> dict:
    """Recover missing equity stops from live protective orders.

    Returns a report listing every open equity position, what was found for
    it, and whether it was (or would be) written. Submits no orders. With
    dry_run=True — the default, and what the route defaults to — it touches
    nothing at all.
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade

    report: dict[str, Any] = {
        "dry_run": dry_run,
        "updated": [],
        "skipped": [],
        "submitted_anything": False,   # this module never places an order
    }

    try:
        book = await broker.get_open_orders(refresh=True)
    except Exception as exc:
        return {**report, "status": "error",
                "reason": f"could not read the order book: {exc}"}
    if book.get("source") != "refreshed":
        return {**report, "status": "unavailable",
                "reason": ("order book came from cache — refusing to record a "
                           "stop from unverified state")}

    # Live positions keyed by symbol: the quantity that must be fully covered.
    try:
        live: dict[str, float] = {}
        for p in await broker.get_equity_positions():
            sym = (getattr(p, "symbol", "") or "").upper()
            if sym:
                live[sym] = float(getattr(p, "quantity", 0) or 0)
    except Exception as exc:
        return {**report, "status": "error",
                "reason": f"could not read live positions: {exc}"}

    stops_by_symbol: dict[str, list[dict]] = {}
    for o in book.get("orders", []):
        if not o.get("is_protective") or float(o.get("remaining") or 0) <= 0:
            continue
        if not o.get("stop_price"):
            continue
        sym = (o.get("symbol") or "").upper()
        if sym:
            stops_by_symbol.setdefault(sym, []).append(o)

    async with AsyncSessionLocal() as session:
        open_trades = (await session.execute(
            select(Trade).where(Trade.status == "open")
        )).scalars().all()

        for t in open_trades:
            spread_type = (getattr(t, "spread_type", "") or "").lower()
            if not spread_type.startswith("equity"):
                continue

            sym = (t.underlying or "").upper()
            entry = float(getattr(t, "credit_received", 0) or 0)
            is_short = spread_type == "equity_short"

            def skip(reason: str) -> None:
                report["skipped"].append(
                    {"trade_id": str(t.id), "ticker": sym, "reason": reason})

            if equity_stop_distance(t) is not None:
                skip("already has a recorded stop — not overwritten")
                continue
            if entry <= 0:
                skip("no usable entry price on the row")
                continue

            position_qty = live.get(sym)
            if position_qty is None or abs(position_qty) <= 0:
                skip("no live broker position for this symbol")
                continue

            candidates = stops_by_symbol.get(sym, [])
            if not candidates:
                skip("no protective stop at the broker")
                continue

            wanted_action = "BUY" if is_short else "SELL"
            wrong_side = [o for o in candidates
                          if (o.get("action") or "").upper() != wanted_action]
            if wrong_side:
                skip(f"protective orders are not all {wanted_action} for an "
                     f"{spread_type} position")
                continue

            stop, covered = _weighted_stop(candidates)
            if stop is None:
                skip("protective orders carry no usable stop price")
                continue

            if abs(covered - abs(position_qty)) > QUANTITY_TOLERANCE:
                skip(f"stops cover {covered:g} of {abs(position_qty):g} shares "
                     f"— partial coverage leaves unbounded risk on the "
                     f"remainder, so notional stays the honest answer")
                continue

            if is_short and stop <= entry:
                skip(f"blended stop {stop:.4f} is not above entry {entry:.4f} "
                     f"for a short")
                continue
            if not is_short and stop >= entry:
                skip(f"blended stop {stop:.4f} is not below entry {entry:.4f} "
                     f"for a long")
                continue
            if abs(entry - stop) < MIN_STOP_DISTANCE_FRACTION * entry:
                skip(f"blended stop {stop:.4f} sits within "
                     f"{MIN_STOP_DISTANCE_FRACTION:.1%} of entry — that is a "
                     f"placeholder, not a stop")
                continue

            qty = abs(int(getattr(t, "quantity", 0) or 0))
            entry_record = {
                "trade_id": str(t.id),
                "ticker": sym,
                "direction": spread_type,
                "entry_price": round(entry, 4),
                "stop_price": round(stop, 4),
                "tranches": len(candidates),
                "shares": qty,
                "risk_before": round(entry * qty, 2),          # notional
                "risk_after": round(abs(entry - stop) * qty, 2),
            }
            report["updated"].append(entry_record)

            if not dry_run:
                t.long_strike = Decimal(str(round(stop, 4)))
                logger.info(
                    "stop backfill: %s stop recorded at %.4f from %d protective "
                    "order(s); risk %.2f -> %.2f",
                    sym, stop, len(candidates),
                    entry_record["risk_before"], entry_record["risk_after"],
                )

        if not dry_run and report["updated"]:
            await session.commit()

    report["status"] = "ok"
    return report
