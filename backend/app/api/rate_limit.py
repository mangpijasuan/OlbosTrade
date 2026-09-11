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


LOGIN_WINDOW_S = 300.0
LOGIN_MAX_ATTEMPTS = 10

_login_log: dict[str, list[float]] = {}


def login_rate_limit(request: Request) -> None:
    """
    Throttle login attempts by source IP, deliberately ignoring X-Api-Key.

    rate_limit() below keys on the API key because on the routes it guards the
    key IS the caller's identity — a shared secret they had to already possess.
    On /api/auth/login there is no such key yet, so that header is nothing but
    attacker-controlled text: sending a fresh random value per request would put
    every attempt in its own bucket and make the limit vacuous. Password
    guessing has to be limited by something the client cannot choose.

    Tighter than the operator limit (10 per 5 minutes, not 20 per minute)
    because a human logging in types a password once or twice, not twenty times.

    Caveat worth knowing: behind a reverse proxy request.client.host is the
    proxy unless it is configured to forward the real address and the app is run
    with --proxy-headers. Without that every client shares one bucket, which
    errs toward refusing logins rather than allowing unlimited guesses, but it
    also means one attacker can lock out everyone. Check the deployment before
    relying on this as the only brake.
    """
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = [t for t in _login_log.get(key, []) if now - t < LOGIN_WINDOW_S]
    if len(recent) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts — try again shortly",
        )
    recent.append(now)
    _login_log[key] = recent


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
