"""
Spot-price cache — short-lived, in-process TTL cache keyed by symbol.
Structurally the same contract as options_chain_cache.py, keyed by symbol
only (not symbol+expiry).

Stress & VaR (risk.py) are polled independently by RiskMonitor.tsx (30s)
and ExecutiveSummary.tsx (15s); without this cache each poll tick would
trigger a live yfinance round-trip. 60s sits between options_chain_cache's
15s (options quotes move in seconds, execution-critical) and
income_screener's 300s (background scan, staleness doesn't matter) — this
is a risk-monitoring read that should still track intraday moves faster
than 5 minutes.

  LIVE     — fetched just now.
  DEGRADED — served from cache, within TTL.
  STALE    — cache entry is past TTL, but served anyway because a live
             re-fetch failed — an explicit fallback, never silently
             presented as LIVE.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

_CACHE: dict[str, tuple[float, float]] = {}  # symbol -> (spot, fetched_at)
TTL_SECONDS = 60.0

_hits = 0
_misses = 0


async def get_spot(symbol: str, fetch: Callable[[], Awaitable[float]]) -> tuple[float, str]:
    """Return (spot, data_status). Calls fetch() on a cache miss or an
    expired entry. If fetch() raises and a (now-expired) cached entry
    exists, falls back to it labeled STALE rather than raising."""
    global _hits, _misses
    key = symbol.upper()
    cached = _CACHE.get(key)
    now = time.monotonic()

    if cached is not None:
        spot, fetched_at = cached
        if now - fetched_at < TTL_SECONDS:
            _hits += 1
            return spot, "DEGRADED"

    try:
        spot = await fetch()
        _CACHE[key] = (spot, now)
        _misses += 1
        return spot, "LIVE"
    except Exception:
        if cached is not None:
            return cached[0], "STALE"
        raise


def stats() -> dict:
    total = _hits + _misses
    return {
        "hits": _hits,
        "misses": _misses,
        "hit_rate": round(_hits / total, 3) if total else None,
        "entries": len(_CACHE),
    }


def clear() -> None:
    """Test-only reset."""
    global _hits, _misses
    _CACHE.clear()
    _hits = 0
    _misses = 0
