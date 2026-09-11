"""
Persistence for options scan rejections — why a spread candidate did not fire.

The options scan has covered the full watchlist every 30 minutes since
2026-08-01 and produced zero closed options trades in the four weeks to the
2026-08-28 assessment. `_record_options_rejection()` already captured every
reason, but only into `_recent_options_signals` — an in-memory list truncated
at 200 entries that dies on restart. Enough to answer "is the scanner broken
right now"; useless for "why has nothing fired in a month."

This gives those reasons a history, so the question can be answered from data
instead of inference. Read it with scripts/options_rejection_report.py.

Upsert semantics: one row per (ticker, strategy, reason, UTC day), with
`occurrences` incremented on repeat and `last_seen_at` advanced. The scan
re-evaluates each symbol ~13 times a day; a row per evaluation would reproduce
the duplication that made signal_outcomes unreadable (see #45/#46). The counter
keeps the frequency without the rows.

Never raises: a diagnostic write must not break the scan it is diagnosing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def record_rejection(
    ticker: str,
    reason: str,
    strategy: Optional[str] = None,
    regime: Optional[str] = None,
    evidence: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """
    Persist (or increment) today's rejection row for this ticker/strategy/reason.

    Returns the row id, or None if the write failed — callers treat this as
    best-effort telemetry, never as a gate.
    """
    try:
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.models.options_scan_rejection import OptionsScanRejection

        stamp = now or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = stamp.astimezone(timezone.utc)
        day_start = stamp.replace(hour=0, minute=0, second=0, microsecond=0)

        # Reason strings are built inline at the call sites and can carry
        # specifics (thresholds, values). Truncate to the column width rather
        # than letting a long one abort the write — a clipped reason still
        # groups correctly on its leading text.
        reason = (reason or "")[:200]

        async with AsyncSessionLocal() as session:
            async with session.begin():
                existing = (await session.execute(
                    select(OptionsScanRejection).where(
                        OptionsScanRejection.ticker == ticker,
                        OptionsScanRejection.strategy.is_(strategy)
                        if strategy is None
                        else OptionsScanRejection.strategy == strategy,
                        OptionsScanRejection.reason == reason,
                        OptionsScanRejection.first_seen_at >= day_start,
                        OptionsScanRejection.first_seen_at < day_start + timedelta(days=1),
                    ).limit(1)
                )).scalar_one_or_none()

                if existing is not None:
                    existing.occurrences += 1
                    existing.last_seen_at = stamp
                    # Keep the first evidence seen: it is the one from the
                    # scan that actually computed a score, and later repeats
                    # usually carry None.
                    if existing.evidence is None and evidence is not None:
                        existing.evidence = evidence
                    return str(existing.id)

                row_id = uuid.uuid4()
                session.add(OptionsScanRejection(
                    id=row_id,
                    ticker=ticker,
                    strategy=strategy,
                    reason=reason,
                    regime=regime,
                    evidence=evidence,
                    occurrences=1,
                    first_seen_at=stamp,
                    last_seen_at=stamp,
                ))
                return str(row_id)
    except Exception as exc:
        logger.warning("record_rejection failed for %s (%s): %s", ticker, reason, exc)
        return None
