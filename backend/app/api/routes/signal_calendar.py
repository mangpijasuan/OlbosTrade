"""
Daily signal calendar — what the desk ranked, and what happened to it.

Read-only. Serves the frozen daily top-3 (daily_signal_snapshots) with each
row's resolution joined on from signal_outcomes, so a day reads as
"we ranked these six, here is how they turned out" rather than a list of
picks with no scorecard.

Resolution is joined rather than stored, because a snapshot row is immutable
and an outcome is not — a signal sits `pending` until it resolves, and copying
that status in would mean rewriting a table whose whole value is that it is
never rewritten.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Query

from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

DEFAULT_DAYS = 30
MAX_DAYS = 180


def _f(v: Any) -> Optional[float]:
    return None if v is None else float(v)


@router.get("/calendar")
async def signal_calendar(days: int = Query(DEFAULT_DAYS, ge=1, le=MAX_DAYS)):
    """The last `days` of frozen top-3 picks, newest day first.

    Each pick carries its resolution when one exists. `pending` is reported as
    pending — an unresolved signal is not a miss, and counting it as one would
    understate the record just as surely as dropping it would flatter it.
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.daily_signal_snapshot import DailySignalSnapshot
    from app.models.signal_outcome import SignalOutcome

    since = date.today() - timedelta(days=days)

    try:
        async with AsyncSessionLocal() as session:
            snaps = (await session.execute(
                select(DailySignalSnapshot)
                .where(DailySignalSnapshot.trade_date >= since)
                .order_by(DailySignalSnapshot.trade_date.desc(),
                          DailySignalSnapshot.action,
                          DailySignalSnapshot.rank)
            )).scalars().all()

            outcome_ids = [s.signal_outcome_id for s in snaps if s.signal_outcome_id]
            outcomes: dict[Any, Any] = {}
            if outcome_ids:
                rows = (await session.execute(
                    select(SignalOutcome).where(SignalOutcome.id.in_(outcome_ids))
                )).scalars().all()
                outcomes = {r.id: r for r in rows}
    except Exception as exc:
        logger.error("signal calendar read failed: %s", exc)
        return {"status": "error", "reason": str(exc), "days": []}

    if not snaps:
        return {"status": "no_snapshots_yet", "days": [],
                "note": ("Snapshots begin accumulating from the first 10:00 ET "
                         "capture after this shipped; history cannot be "
                         "backfilled without reintroducing hindsight.")}

    by_day: dict[str, dict] = {}
    for s in snaps:
        key = s.trade_date.isoformat()
        day = by_day.setdefault(key, {"date": key, "BUY": [], "SELL": []})
        o = outcomes.get(s.signal_outcome_id)
        day[s.action].append({
            "rank": s.rank,
            "ticker": s.ticker,
            "opportunity_score": s.opportunity_score,
            "confidence": _f(s.confidence),
            "entry_price": _f(s.entry_price),
            "stop_price": _f(s.stop_price),
            "target_price": _f(s.target_price),
            "regime": s.regime,
            "generated_at": s.generated_at.isoformat() if s.generated_at else None,
            # Resolution, or an explicit unresolved marker — never a guess.
            "outcome": (o.status if o else None),
            "exit_price": _f(getattr(o, "exit_price", None)) if o else None,
            "days_to_resolve": getattr(o, "days_to_resolve", None) if o else None,
            "max_favorable_pct": _f(getattr(o, "max_favorable_pct", None)) if o else None,
            "max_adverse_pct": _f(getattr(o, "max_adverse_pct", None)) if o else None,
        })

    days_out = list(by_day.values())

    # Scorecard across everything resolved in the window. Deliberately reports
    # the unresolved count alongside, so a small denominator is visible rather
    # than hidden behind a confident-looking percentage.
    picks = [p for d in days_out for side in ("BUY", "SELL") for p in d[side]]
    resolved = [p for p in picks if p["outcome"] in ("target_hit", "stop_hit", "expired")]
    hits = [p for p in resolved if p["outcome"] == "target_hit"]

    return {
        "status": "ok",
        "days": days_out,
        "summary": {
            "trading_days": len(days_out),
            "picks": len(picks),
            "resolved": len(resolved),
            "pending": len(picks) - len(resolved),
            "target_hit": len(hits),
            "hit_rate_pct": (round(len(hits) / len(resolved) * 100, 1)
                             if resolved else None),
        },
    }
