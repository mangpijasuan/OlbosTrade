"""
Rotation correlation cache — periodically-refreshed, in-process cache of
which currently-open equity tickers sit in a flagged correlation cluster
(pct_of_capital over portfolio_engine.CORRELATION_MAX_CLUSTER_PCT).

Structurally the same shape as spot_price_cache.py (a plain module-level
dict + time.monotonic(), not a class) but push- rather than pull-based:
compute_correlation_clusters() needs a live yfinance fetch per ticker
(see portfolio.py's GET /correlation route), which must never sit inside
position_rotation.py's rotate_for_new_equity_entry() money-path. Instead,
refresh() is called periodically by main.py's background scheduler, and
rotation only ever does a synchronous, non-blocking dict lookup via
in_flagged_cluster().

in_flagged_cluster() returns None ("no signal") whenever the cache is
stale, missing, or doesn't cover a given ticker — callers must treat that
as neutral, never as "definitely not clustered."
"""

from __future__ import annotations

import time
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

REFRESH_INTERVAL_S = 20 * 60
# Generous enough that one missed/slow refresh cycle doesn't blank the
# signal, tight enough that a genuinely dead scheduler goes neutral within
# well under an hour.
STALE_AFTER_S = REFRESH_INTERVAL_S * 2

# ticker -> its flagged cluster's enriched dict (tickers/avg_correlation/
# combined_risk_dollars/pct_of_capital), only for clusters that actually
# breached CORRELATION_MAX_CLUSTER_PCT.
_ticker_to_cluster: dict[str, dict] = {}
# Every ticker that was part of the last successful computation's input
# pool — lets in_flagged_cluster distinguish "covered but not clustered"
# (real False) from "never seen" (None, no signal).
_covered_tickers: set[str] = set()
_computed_at: Optional[float] = None


def in_flagged_cluster(ticker: str) -> Optional[bool]:
    """True if ticker is currently in a flagged correlation cluster, False
    if the cache is fresh and covers this ticker but it isn't clustered,
    None if the cache is missing, stale, or doesn't cover this ticker.
    Never raises, never blocks — pure in-memory lookup."""
    if _computed_at is None:
        return None
    if time.monotonic() - _computed_at > STALE_AFTER_S:
        return None
    key = (ticker or "").upper()
    if key not in _covered_tickers:
        return None
    return key in _ticker_to_cluster


def _store(flagged_clusters: list[dict], covered_tickers: set[str]) -> None:
    global _ticker_to_cluster, _covered_tickers, _computed_at
    ticker_to_cluster: dict[str, dict] = {}
    for cluster in flagged_clusters:
        for t in cluster.get("tickers", []):
            ticker_to_cluster[t.upper()] = cluster
    _ticker_to_cluster = ticker_to_cluster
    _covered_tickers = {t.upper() for t in covered_tickers}
    _computed_at = time.monotonic()


def clear() -> None:
    """Test-only reset."""
    global _ticker_to_cluster, _covered_tickers, _computed_at
    _ticker_to_cluster = {}
    _covered_tickers = set()
    _computed_at = None


async def refresh() -> None:
    """Refresh the rotation-scoped correlation cluster cache from currently
    open equity positions. Mirrors portfolio.py's GET /correlation route's
    fetch/compute pipeline (same _yf_bars call, same concurrency bound,
    same portfolio_engine functions) but writes to this module's cache
    instead of returning a response.

    On any degrade case (fewer than 2 open equity tickers, DB failure,
    fetch/alignment failure) the cache is left untouched — it ages toward
    staleness rather than being poisoned with a wrong or empty-but-fresh
    result."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.account_state import get_account_value
    from app.services.portfolio_engine import (
        CORRELATION_MAX_CLUSTER_PCT,
        align_price_series,
        cluster_concentration_flags,
        compute_correlation_clusters,
        position_risk_dollars,
    )

    try:
        async with AsyncSessionLocal() as session:
            open_trades = (
                await session.execute(select(Trade).where(Trade.status == "open"))
            ).scalars().all()
    except Exception as exc:
        logger.warning("rotation correlation refresh: DB read failed: %s", exc)
        return

    equity_opens = [
        t for t in open_trades
        if (t.spread_type or "").lower() in ("equity_long", "equity_short")
    ]
    risk_by_underlying: dict[str, float] = {}
    for t in equity_opens:
        risk_by_underlying[t.underlying] = (
            risk_by_underlying.get(t.underlying, 0.0) + position_risk_dollars(t)
        )

    tickers = sorted(risk_by_underlying.keys())
    if len(tickers) < 2:
        return

    try:
        import asyncio
        from app.main import _yf_bars

        sem = asyncio.Semaphore(5)

        async def _fetch(ticker: str):
            async with sem:
                try:
                    return ticker, await _yf_bars(ticker, limit=60)
                except Exception:
                    return ticker, []

        fetched = await asyncio.gather(*(_fetch(t) for t in tickers))
    except Exception as exc:
        logger.warning("rotation correlation refresh: bar fetch failed: %s", exc)
        return

    bars_by_ticker = {t: bars for t, bars in fetched if bars}
    aligned, _excluded = align_price_series(bars_by_ticker)
    if len(aligned) < 2:
        return

    try:
        account_value = await get_account_value()
        clustered = compute_correlation_clusters(aligned)
        enriched, _flags = cluster_concentration_flags(
            clustered["clusters"], risk_by_underlying, account_value,
        )
    except Exception as exc:
        logger.warning("rotation correlation refresh: clustering failed: %s", exc)
        return

    flagged = [
        c for c in enriched
        if account_value > 0 and c["pct_of_capital"] > CORRELATION_MAX_CLUSTER_PCT * 100
    ]
    _store(flagged_clusters=flagged, covered_tickers=set(tickers))
