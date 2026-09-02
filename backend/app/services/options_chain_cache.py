"""
Options-chain cache — short-lived, in-process TTL cache keyed by
(symbol, expiry). Shape matches orderflow_engine.py's existing dict-cache.

Options quotes go stale in seconds during market hours, so this is
deliberately short (15s) — long enough to absorb duplicate/rapid requests
for the same chain without ever presenting data old enough to matter as if
it were live. Every response carries an explicit data_status so the caller
(and the frontend) never has to guess:

  LIVE     — fetched from IBKR just now.
  DEGRADED — served from cache, within TTL.
  STALE    — cache entry is past TTL, but served anyway because a live
             re-fetch failed/timed out — an explicit fallback, never
             silently presented as LIVE.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

_CACHE: dict[tuple[str, str], tuple[dict, float]] = {}  # (symbol, expiry) -> (chain, fetched_at)
TTL_SECONDS = 15.0

_hits = 0
_misses = 0


async def get_chain(
    symbol: str, expiry: str, fetch: Callable[[], Awaitable[dict]]
) -> tuple[dict, str]:
    """Return (chain_dict, data_status). Calls fetch() on a cache miss or
    an expired entry. If fetch() raises and a (now-expired) cached entry
    exists, falls back to it labeled STALE rather than raising — the
    caller decides whether that's acceptable, but it's never mislabeled."""
    global _hits, _misses
    key = (symbol.upper(), expiry)
    cached = _CACHE.get(key)
    now = time.monotonic()

    if cached is not None:
        chain, fetched_at = cached
        if now - fetched_at < TTL_SECONDS:
            _hits += 1
            return chain, "DEGRADED"

    try:
        chain = await fetch()
        _CACHE[key] = (chain, now)
        _misses += 1
        return chain, "LIVE"
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
