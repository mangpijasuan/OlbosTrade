"""
Real ticker -> sector resolution, cached off the money path.

portfolio_engine.SECTORS is a 19-entry hand-written map, and only 8 of those
entries are tickers this desk actually trades — the equity watchlist is 100
symbols. Everything else resolved to "Unknown", which three separate risk
gates then treated as if it were a sector. On 2026-08-29 that single bucket
held 94% of the book and blocked entries with reasons like "Sector
concentration: Unknown (GILD) would be 94.1%" — GILD and AEP and COST are not
one sector, and a cap that says they are is asserting something false.

Two things were wrong and both need fixing: the missing data (here) and the
treatment of absent data as a category (portfolio_engine.is_cappable_sector).

yfinance carries the sector on Ticker.info. It is static data — a company's
sector does not move — so it is fetched on a slow scheduler loop and read
synchronously from memory by the gates, never fetched inside them.

Deliberately in-memory rather than a table, matching rotation_correlation_cache
and spot_price_cache. The cost is that a restart leaves every ticker
unresolved until the first refresh completes, during which the sector cap
simply does not apply. That is the same direction this module already fails in
for an unresolved ticker, so a cold start is a weaker check rather than a
wrong one — which is the trade this whole change is about.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

REFRESH_INTERVAL_S = 24 * 60 * 60      # sector membership changes ~never
STALE_AFTER_S = 7 * 24 * 60 * 60       # a week without a successful refresh
MAX_CONCURRENT_FETCHES = 5             # matches the /correlation route's own cap

# yfinance's vocabulary is the canonical one here, because it is where almost
# every resolution comes from. The static map in portfolio_engine is written to
# match it, so a cold-cache fallback and a warm-cache hit put the same company
# in the same bucket. Two names for one sector would split it and understate
# concentration — a quieter failure than the one being fixed, and worse.
_CANONICAL = {
    "technology": "Technology",
    "healthcare": "Healthcare",
    "financial services": "Financial Services",
    "consumer cyclical": "Consumer Cyclical",
    "consumer defensive": "Consumer Defensive",
    "communication services": "Communication Services",
    "industrials": "Industrials",
    "energy": "Energy",
    "utilities": "Utilities",
    "real estate": "Real Estate",
    "basic materials": "Basic Materials",
}

_sectors: dict[str, str] = {}
_resolved_at: Optional[float] = None


def canonical_sector(raw: Optional[str]) -> Optional[str]:
    """Map a provider's sector label into this system's vocabulary."""
    if not raw:
        return None
    return _CANONICAL.get(str(raw).strip().lower())


def sector_for_cached(ticker: str) -> Optional[str]:
    """Resolved sector, or None when unknown, unresolved or stale.

    Never raises, never blocks, never fetches — the risk gates call this
    synchronously and must not acquire a network dependency by doing so.
    """
    if _resolved_at is None:
        return None
    if time.monotonic() - _resolved_at > STALE_AFTER_S:
        return None
    return _sectors.get((ticker or "").upper())


def clear() -> None:
    """Test-only reset (mirrors spot_price_cache.clear)."""
    global _sectors, _resolved_at
    _sectors = {}
    _resolved_at = None


def _fetch_one(ticker: str) -> Optional[str]:
    """Blocking yfinance read. Runs in a thread, never on the event loop."""
    try:
        import yfinance as yf
        return canonical_sector((yf.Ticker(ticker).info or {}).get("sector"))
    except Exception as exc:
        logger.debug("sector lookup failed for %s: %s", ticker, exc)
        return None


async def refresh(tickers: Optional[list[str]] = None) -> dict:
    """Resolve sectors for the watchlist plus any open position.

    Partial results are kept: a ticker that resolves is worth caching even if
    its neighbour timed out. A ticker that fails keeps whatever it had rather
    than being downgraded to unknown on one bad fetch.
    """
    global _sectors, _resolved_at

    if tickers is None:
        from app.core.config import settings
        tickers = settings.get_equity_watchlist()
        try:
            from sqlalchemy import select

            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade
            async with AsyncSessionLocal() as session:
                rows = (await session.execute(
                    select(Trade).where(Trade.status == "open")
                )).scalars().all()
            tickers = list({*tickers, *[(t.underlying or "").upper()
                                        for t in rows if t.underlying]})
        except Exception as exc:
            # An open position missing from the refresh just stays unresolved.
            logger.warning("sector refresh could not read open trades: %s", exc)

    wanted = [t for t in {(t or "").upper() for t in tickers} if t]
    if not wanted:
        return {"resolved": 0, "unresolved": 0}

    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def one(sym: str) -> tuple[str, Optional[str]]:
        async with sem:
            return sym, await asyncio.to_thread(_fetch_one, sym)

    results = await asyncio.gather(*(one(s) for s in wanted),
                                   return_exceptions=True)

    resolved = dict(_sectors)
    added = 0
    for r in results:
        if isinstance(r, BaseException):
            continue
        sym, sector = r
        if sector:
            if resolved.get(sym) != sector:
                added += 1
            resolved[sym] = sector

    _sectors = resolved
    _resolved_at = time.monotonic()
    unresolved = [s for s in wanted if s not in _sectors]
    logger.info(
        "sector cache: %d/%d resolved (%d new/changed), %d still unknown",
        len(wanted) - len(unresolved), len(wanted), added, len(unresolved),
    )
    return {"resolved": len(wanted) - len(unresolved),
            "unresolved": len(unresolved),
            "unknown_tickers": sorted(unresolved)[:20]}
