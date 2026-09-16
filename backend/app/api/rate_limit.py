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

    request.client.host is only the real caller when the deployment cooperates,
    and for a while this one did not. The caveat used to end "check the
    deployment before relying on this"; the deployment was checked, and it was
    broken: the image CMD ran uvicorn WITHOUT --proxy-headers, so every request
    carried the frontend proxy's address and all callers shared one bucket.
    Ten failed logins from anyone locked out everybody for five minutes — a
    denial of service against login, not a brake on guessing.

    Fixed in docker-compose.hetzner.yml, which now passes --proxy-headers
    --forwarded-allow-ips=*. What makes the value trustworthy is the frontend:
    it sets X-Forwarded-For from $remote_addr — overwriting, not appending — so
    a header arriving from it was written by the proxy and never by the caller,
    and uvicorn sees one proxy-authored value and reports it as client.host.

    What that does NOT establish, and an earlier version of this docstring
    wrongly said it did: that every request has been through the frontend. The
    backend publishes no host port, but it does join the shared docker_default
    network (it has to — that is where the IBKR gateway resolves), so any
    container on that network can reach uvicorn directly and forge the header
    to dodge its own login limit. The bar is a container on the operator's own
    private network rather than any internet caller, which is why this is still
    a large net improvement over one shared bucket; it is not the same as
    trusting only the proxy. Closing it means not depending on topology at all
    — e.g. requiring a shared-secret header from the frontend before believing
    X-Forwarded-For.

    Two more things to know. Behind Caddy the frontend's own $remote_addr is
    Caddy, so Caddy-routed callers still share a bucket until
    TRUSTED_PROXY_CIDR names Caddy's subnet (frontend/docker-entrypoint.sh,
    deploy/hetzner/.env.example). And the flag is deliberately per-stack:
    docker-compose.yml and docker-compose.prod.yml publish the backend port, so
    any caller on the host network could connect directly and forge the header
    — --proxy-headers must not be copied there.
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
