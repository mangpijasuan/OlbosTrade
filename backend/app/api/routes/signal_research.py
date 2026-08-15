"""
Signal research API — forward-return study over every tracked equity signal.

Answers: of the signals this system generated, how many actually moved to
target vs stop, and how many trading days did that take. Complements Mode
Analytics (which only covers the handful of trades that got executed) with
a much larger, unbiased sample: every routable signal, traded or not.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter()


async def _load_outcomes() -> list[dict]:
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.signal_outcome import SignalOutcome

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(SignalOutcome))).scalars().all()

    return [
        {
            "id":                str(r.id),
            "ticker":            r.ticker,
            "action":            r.action,
            "confidence":        float(r.confidence),
            "status":            r.status,
            "generated_at":      r.generated_at.isoformat() if r.generated_at else None,
            "resolved_at":       r.resolved_at.isoformat() if r.resolved_at else None,
            "days_to_resolve":   r.days_to_resolve,
            "entry_price":       float(r.entry_price),
            "target_price":      float(r.target_price),
            "stop_price":        float(r.stop_price),
            "exit_price":        float(r.exit_price) if r.exit_price is not None else None,
            "target_move_pct":   float(r.target_move_pct) if r.target_move_pct is not None else None,
            "max_favorable_pct": float(r.max_favorable_pct) if r.max_favorable_pct is not None else None,
            "max_adverse_pct":   float(r.max_adverse_pct) if r.max_adverse_pct is not None else None,
        }
        for r in rows
    ]


@router.get("/outcomes")
async def get_signal_outcomes():
    """
    Hit rate / days-to-resolve breakdown across every tracked equity signal
    — not just the ones that were traded. See signal_outcome_tracker.py.
    """
    from app.services.signal_outcome_tracker import compute_signal_outcome_stats

    outcomes = await _load_outcomes()
    if not outcomes:
        return {
            "message": (
                "No signals tracked yet. Outcomes are recorded automatically as "
                "the equity scanner runs and resolved every 6 hours against fresh "
                "daily bars."
            ),
            "total": 0,
        }
    return compute_signal_outcome_stats(outcomes)


@router.get("/outcomes/raw")
async def get_signal_outcomes_raw(
    limit: int = Query(200, le=1000),
    status: Optional[str] = Query(None, description="pending | target_hit | stop_hit | expired"),
):
    """Raw per-signal outcome rows, most recent first."""
    outcomes = await _load_outcomes()
    if status:
        outcomes = [o for o in outcomes if o["status"] == status]
    outcomes.sort(key=lambda o: o["generated_at"] or "", reverse=True)
    return {"outcomes": outcomes[:limit], "total": len(outcomes)}
