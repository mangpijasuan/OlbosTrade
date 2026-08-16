"""
In-process rate limiting for auth-gated mutate routes (order placement,
approvals, kill-switch trigger). No Redis in this stack — single-process
Hetzner deployment — so this matches the existing in-memory dict+TTL
pattern already used by options_chain_cache.py / orderflow_engine.py, just
keyed per-client with a list of recent request timestamps instead of a
single cached value.

Applied alongside require_api_key/require_api_key_configured (app/api/
deps.py), not instead of — this only limits request rate, it doesn't
replace the identity check.
"""
from __future__ import annotations

import time

from fastapi import Header, HTTPException, Request

WINDOW_S = 60.0
MAX_REQUESTS = 20

_request_log: dict[str, list[float]] = {}


def _client_key(request: Request, x_api_key: str) -> str:
    """Prefer the API key as identity — it's already the primary identity
    on every route this guards. Falls back to client IP only when no key
    is configured (e.g. local dev, where require_api_key itself no-ops)."""
    return x_api_key or (request.client.host if request.client else "unknown")


def rate_limit(request: Request, x_api_key: str = Header(default="", alias="X-Api-Key")) -> None:
    """20 requests / 60s per client on order-placement/kill-switch-adjacent
    routes — generous for a human operator clicking approve/manual-trade/
    kill-switch, well below anything a script hammering a leaked or
    guessed key could usefully exploit."""
    key = _client_key(request, x_api_key)
    now = time.monotonic()
    recent = [t for t in _request_log.get(key, []) if now - t < WINDOW_S]
    if len(recent) >= MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded — max {MAX_REQUESTS} requests per {WINDOW_S:.0f}s",
        )
    recent.append(now)
    _request_log[key] = recent
