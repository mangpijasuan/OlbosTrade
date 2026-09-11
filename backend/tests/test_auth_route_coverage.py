"""
Default-deny coverage: every route is either authenticated or deliberately public.

This is the actual deliverable of auth Phase 2. The wiring is easy; what is
hard is that it stays true. There are ~160 registered routes, and the failure
mode of per-route auth is that someone adds route 161 without the dependency
and nobody notices until it matters.

So rather than trusting review, this test enumerates what FastAPI actually
registered and asserts each path is covered by the app-level dependency or
named in the allowlist. A new public path has to be added to PUBLIC_EXACT /
PUBLIC_PREFIXES on purpose, in a diff, where it can be argued about.
"""

from __future__ import annotations

import pytest

from app.api.auth_deps import PUBLIC_EXACT, PUBLIC_PREFIXES, is_public_path


def _registered_paths() -> list[str]:
    import app.main as main_mod
    return sorted({
        r.path for r in main_mod.app.routes
        if hasattr(r, "methods") and getattr(r, "path", "").startswith(("/api", "/health", "/ws"))
    })


def test_the_app_carries_a_global_auth_dependency():
    """
    Protection is applied once, on the app, not per route. If this ever becomes
    per-route the coverage guarantee below silently stops meaning anything.
    """
    import app.main as main_mod
    from app.api.auth_deps import require_session

    # FastAPI(dependencies=[...]) lands on app.router.dependencies, not
    # app.dependencies — checked against the running app rather than assumed.
    deps = getattr(main_mod.app.router, "dependencies", None) or []
    assert any(getattr(d, "dependency", None) is require_session for d in deps), (
        "require_session must be an app-level dependency — per-route auth is "
        "how route 161 ships unprotected"
    )


def test_every_registered_route_is_protected_or_explicitly_public():
    unprotected = [p for p in _registered_paths() if is_public_path(p)]
    # Everything public must be there ON PURPOSE. If this list grows, the diff
    # is the review.
    expected_public = {
        "/api/auth/login",
        "/api/auth/logout",
        # Both health paths: the container healthcheck and the nginx probe
        # cannot hold a session, and a healthcheck that 401s marks a working
        # container unhealthy and restarts it in a loop.
        "/api/health",
        "/health",
    }
    surprising = set(unprotected) - expected_public
    assert not surprising, (
        f"These routes are reachable without a session: {sorted(surprising)}. "
        "Either protect them, or add them to expected_public here with a reason."
    )


def test_health_stays_public():
    """Container health checks cannot log in."""
    assert is_public_path("/api/health")
    assert is_public_path("/health")


def test_login_is_public_but_me_is_not():
    """Obvious, and exactly the pair worth pinning."""
    assert is_public_path("/api/auth/login")
    assert not is_public_path("/api/auth/me")


@pytest.mark.parametrize("path", [
    "/api/trade-desk/execute",
    "/api/risk/kill-switch/trigger",
    "/api/portfolio/positions",
    "/api/equity/signals",
    "/api/options/signals",
    "/api/backtest/run",
])
def test_sensitive_paths_are_never_public(path):
    assert not is_public_path(path), f"{path} must require a session"


def test_allowlist_prefixes_cannot_swallow_the_api():
    """
    A prefix like "/" or "/api" in PUBLIC_PREFIXES would silently make
    everything public while every other test still passed.
    """
    for prefix in PUBLIC_PREFIXES:
        assert prefix not in ("", "/", "/api"), f"dangerously broad public prefix: {prefix!r}"
        assert not "/api".startswith(prefix.rstrip("/")) or prefix.startswith("/api/"), (
            f"prefix {prefix!r} would expose API routes"
        )


def test_exact_allowlist_contains_no_api_wildcards():
    for path in PUBLIC_EXACT:
        assert not path.endswith("*"), f"wildcards are not matched literally: {path!r}"
