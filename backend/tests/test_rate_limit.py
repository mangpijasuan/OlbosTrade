"""
Tests for the in-process rate limiter applied to auth-gated mutate routes
(order placement, approvals, kill-switch trigger). No Redis in this
stack — single-process deployment — so this is a plain in-memory sliding
window, matching test_api_deps.py's direct-call style (call the dependency
function directly, not through TestClient/HTTP).

Run with: pytest tests/test_rate_limit.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import rate_limit as rl


@pytest.fixture(autouse=True)
def _reset_log():
    rl._request_log.clear()
    yield
    rl._request_log.clear()


def _request(ip: str = "1.2.3.4") -> MagicMock:
    req = MagicMock()
    req.client.host = ip
    return req


def test_requests_under_the_limit_all_pass():
    req = _request()
    for _ in range(rl.MAX_REQUESTS):
        rl.rate_limit(req, x_api_key="test-key")  # must not raise


def test_request_over_the_limit_raises_429():
    req = _request()
    for _ in range(rl.MAX_REQUESTS):
        rl.rate_limit(req, x_api_key="test-key")
    with pytest.raises(HTTPException) as exc_info:
        rl.rate_limit(req, x_api_key="test-key")
    assert exc_info.value.status_code == 429


def test_different_api_keys_have_independent_limits():
    req = _request()
    for _ in range(rl.MAX_REQUESTS):
        rl.rate_limit(req, x_api_key="key-a")
    # key-a is now at the limit, but key-b must be unaffected.
    rl.rate_limit(req, x_api_key="key-b")  # must not raise


def test_falls_back_to_client_ip_when_no_api_key():
    req_a = _request(ip="1.1.1.1")
    req_b = _request(ip="2.2.2.2")
    for _ in range(rl.MAX_REQUESTS):
        rl.rate_limit(req_a, x_api_key="")
    with pytest.raises(HTTPException):
        rl.rate_limit(req_a, x_api_key="")
    # A different client IP (still no key) must have its own bucket.
    rl.rate_limit(req_b, x_api_key="")  # must not raise


def test_old_requests_outside_the_window_do_not_count(monkeypatch):
    req = _request()
    t = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: t[0])

    for _ in range(rl.MAX_REQUESTS):
        rl.rate_limit(req, x_api_key="test-key")
    with pytest.raises(HTTPException):
        rl.rate_limit(req, x_api_key="test-key")

    # Advance past the window — the old requests should no longer count.
    t[0] += rl.WINDOW_S + 1
    rl.rate_limit(req, x_api_key="test-key")  # must not raise
