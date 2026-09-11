"""
Login / logout / me, and the default-deny dependency, exercised over HTTP.

There is no aiosqlite in this stack and Postgres is not available in CI, so
the database is a small in-memory stand-in that answers the three queries the
auth code actually issues. That is a real limitation and worth naming: these
tests prove the route logic and the cookie lifecycle, not the SQL. What they
are for is the behaviour that is expensive to get wrong — that a bad password
and a nonexistent account are indistinguishable, that logout revokes
server-side rather than only clearing a cookie, and that a protected route
without a session returns 401 instead of data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import Depends, FastAPI

import app.api.rate_limit as rate_limit_mod
import app.core.database as db_mod
from app.api.auth_deps import require_session
from app.api.routes.auth import router as auth_router
from app.core.config import settings
from app.models.user import User, UserSession
from app.services.auth_service import (
    SESSION_COOKIE_NAME, hash_password, hash_token,
)

PASSWORD = "correct horse battery staple"


# ── in-memory stand-in for the database ──────────────────────────────────────

class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None


class _Store:
    def __init__(self):
        self.users: list[User] = []
        self.sessions: list[UserSession] = []
        self.commits = 0


class _FakeSession:
    """Answers exactly the three statements the auth code issues, dispatching
    on the entities the select names rather than on call order — so a query
    the code stops making shows up as an empty result, not a silent pass."""

    def __init__(self, store: _Store):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        entities = [d["entity"].__name__ for d in stmt.column_descriptions]
        params = stmt.compile().params

        if entities == ["User"]:
            email = params.get("email_1")
            return _Result([u for u in self.store.users if u.email == email])

        if entities == ["UserSession"]:                       # logout lookup
            th = params.get("token_hash_1")
            return _Result([s for s in self.store.sessions if s.token_hash == th])

        if entities == ["UserSession", "User"]:               # session -> user join
            th = params.get("token_hash_1")
            rows = []
            for s in self.store.sessions:
                if s.token_hash != th:
                    continue
                user = next((u for u in self.store.users if u.id == s.user_id), None)
                if user is not None:
                    rows.append((s, user))
            return _Result(rows)

        raise AssertionError(f"unexpected query over {entities}")

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()                             # normally set at flush
        (self.store.sessions if isinstance(obj, UserSession) else self.store.users).append(obj)

    async def commit(self):
        self.store.commits += 1


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(db_mod, "AsyncSessionLocal", lambda: _FakeSession(s))
    # Rate limiting is process-global and keyed on client IP; every test here
    # shares the same test-client host, so without this the later tests inherit
    # earlier attempts and start failing with 429.
    rate_limit_mod._login_log.clear()
    rate_limit_mod._request_log.clear()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)   # test client is http
    return s


@pytest.fixture
def user(store):
    u = User(id=uuid.uuid4(), email="trader@example.com",
             password_hash=hash_password(PASSWORD), tier="pro", is_active=True)
    store.users.append(u)
    return u


@pytest.fixture
def client():
    app = FastAPI(dependencies=[Depends(require_session)])
    app.include_router(auth_router)

    @app.get("/api/portfolio/positions")
    async def _positions():
        return {"positions": []}

    @app.get("/api/health")
    async def _health():
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _login(client, email="trader@example.com", password=PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


# ── login ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_correct_credentials_return_a_session_cookie(client, user):
    async with client:
        r = await _login(client)
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "trader@example.com"
    assert r.json()["user"]["tier"] == "pro"
    assert SESSION_COOKIE_NAME in r.cookies


@pytest.mark.asyncio
async def test_the_cookie_is_httponly_and_samesite_lax(client, user):
    async with client:
        r = await _login(client)
    raw = r.headers["set-cookie"].lower()
    # httponly is what keeps XSS from lifting the session; samesite is what
    # keeps another origin from spending it.
    assert "httponly" in raw
    assert "samesite=lax" in raw


@pytest.mark.asyncio
async def test_the_plaintext_token_is_never_stored(client, user, store):
    async with client:
        r = await _login(client)
    token = r.cookies[SESSION_COOKIE_NAME]
    stored = store.sessions[0].token_hash
    assert stored != token
    assert stored == hash_token(token)


@pytest.mark.asyncio
async def test_login_records_last_login(client, user):
    async with client:
        await _login(client)
    assert user.last_login_at is not None


@pytest.mark.parametrize("email,password", [
    ("trader@example.com", "wrong password entirely"),   # real user, bad password
    ("nobody@example.com", PASSWORD),                    # no such user
    ("nobody@example.com", "wrong password entirely"),   # neither
])
@pytest.mark.asyncio
async def test_every_failure_is_the_same_401(client, user, email, password):
    """
    Account enumeration matters more here than on most apps: a confirmed
    OlbosTrade address is, by construction, someone with a brokerage account.
    So "no such user" and "wrong password" must be byte-identical.
    """
    async with client:
        r = await _login(client, email, password)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_no_cookie_is_set_on_a_failed_login(client, user):
    async with client:
        r = await _login(client, password="wrong password entirely")
    assert SESSION_COOKIE_NAME not in r.cookies
    assert "set-cookie" not in r.headers


@pytest.mark.asyncio
async def test_deactivated_user_cannot_log_in(client, user, store):
    user.is_active = False
    async with client:
        r = await _login(client)
    assert r.status_code == 401
    assert not store.sessions


@pytest.mark.asyncio
async def test_email_is_matched_case_insensitively(client, user):
    async with client:
        r = await _login(client, email="  TRADER@Example.COM  ")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_404s_while_auth_is_disabled(client, user, monkeypatch):
    """The feature ships off. Until an operator turns it on, the route must not
    mint sessions that the rest of the app is not yet checking."""
    monkeypatch.setattr(settings, "auth_enabled", False)
    async with client:
        r = await _login(client)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_login_is_rate_limited(client, user):
    async with client:
        codes = [(await _login(client, password="wrong password entirely")).status_code
                 for _ in range(rate_limit_mod.LOGIN_MAX_ATTEMPTS + 2)]
    assert 429 in codes, "unlimited login attempts is unlimited password guessing"


@pytest.mark.asyncio
async def test_rotating_the_api_key_header_does_not_reset_the_login_limit(client, user):
    """
    The general rate_limit() buckets by X-Api-Key, because on the routes it
    guards that key IS the caller's identity. On login there is no key yet, so
    the header is attacker-controlled text: if login used that limiter, a fresh
    random value per request would put every attempt in its own bucket and make
    the limit vacuous. Found by review, not by the original tests.
    """
    async with client:
        codes = []
        for i in range(rate_limit_mod.LOGIN_MAX_ATTEMPTS + 2):
            r = await client.post(
                "/api/auth/login",
                json={"email": "trader@example.com", "password": "wrong password"},
                headers={"X-Api-Key": f"rotating-value-{i}"},
            )
            codes.append(r.status_code)
    assert 429 in codes, "login throttling must not be keyed on a header the client picks"


# ── /status: what the frontend boots on ──────────────────────────────────────

@pytest.mark.asyncio
async def test_status_reports_auth_off_without_requiring_a_session(client, user, monkeypatch):
    """
    The reason this endpoint exists. With auth disabled /me returns 401, which
    a client cannot distinguish from "logged out" — so it would show a login
    page on an instance where login returns 404.
    """
    monkeypatch.setattr(settings, "auth_enabled", False)
    async with client:
        r = await client.get("/api/auth/status")
    assert r.status_code == 200
    assert r.json() == {"auth_enabled": False, "authenticated": False, "user": None}


@pytest.mark.asyncio
async def test_status_is_reachable_without_a_session_when_auth_is_on(client, user):
    """It has to be public, or the client can never learn it needs to log in."""
    async with client:
        r = await client.get("/api/auth/status")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_enabled"] is True
    assert body["authenticated"] is False
    assert body["user"] is None


@pytest.mark.asyncio
async def test_status_identifies_the_caller_once_signed_in(client, user):
    async with client:
        await _login(client)
        r = await client.get("/api/auth/status")
    body = r.json()
    assert body["authenticated"] is True
    assert body["user"]["email"] == "trader@example.com"
    assert body["user"]["tier"] == "pro"


@pytest.mark.asyncio
async def test_status_tells_an_anonymous_caller_nothing_about_anyone(client, user):
    """
    Public endpoint, so it must not become a directory. It reports only the
    caller's own session — never that an account exists.
    """
    async with client:
        r = await client.get("/api/auth/status")
    assert r.json()["user"] is None
    assert "trader@example.com" not in r.text


@pytest.mark.asyncio
async def test_status_does_not_leak_the_password_hash(client, user):
    async with client:
        await _login(client)
        r = await client.get("/api/auth/status")
    assert "password" not in r.text.lower()
    assert "argon2" not in r.text.lower()


# ── protected routes ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_protected_route_rejects_a_request_with_no_cookie(client, user):
    async with client:
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_rejects_a_forged_cookie(client, user):
    async with client:
        client.cookies.set(SESSION_COOKIE_NAME, "made-up-token")
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_then_access_then_logout_then_denied(client, user, store):
    """The whole lifecycle in one test, because each half is only meaningful
    if the other holds."""
    async with client:
        assert (await _login(client)).status_code == 200

        assert (await client.get("/api/portfolio/positions")).status_code == 200
        assert (await client.get("/api/auth/me")).json()["user"]["email"] == "trader@example.com"

        assert (await client.post("/api/auth/logout")).status_code == 200
        assert store.sessions[0].revoked_at is not None, "logout must revoke server-side"

        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_a_stolen_token_stops_working_after_logout(client, user, store):
    """
    Clearing the cookie only disarms the polite client. This replays the token
    from a fresh client after logout — the case a JWT would still accept, and
    the reason sessions are database rows here.
    """
    async with client:
        token = (await _login(client)).cookies[SESSION_COOKIE_NAME]
        await client.post("/api/auth/logout")

        client.cookies.set(SESSION_COOKIE_NAME, token)
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_expired_session_is_rejected(client, user, store):
    async with client:
        await _login(client)
        store.sessions[0].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_deactivating_a_user_kills_live_sessions_immediately(client, user):
    """Not at the next expiry — a departing user or a compromised laptop is
    exactly when twelve more hours of access is unacceptable."""
    async with client:
        await _login(client)
        assert (await client.get("/api/portfolio/positions")).status_code == 200
        user.is_active = False
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_health_stays_reachable_without_a_session(client, user):
    async with client:
        r = await client.get("/api/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_me_401s_without_a_session(client, user):
    async with client:
        r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_without_a_session_is_not_an_error(client, user):
    """Logout has to be idempotent, or a double-click on a timed-out tab shows
    the user a stack trace."""
    async with client:
        r = await client.post("/api/auth/logout")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_logout_does_not_claim_success_when_revocation_failed(client, user, store, monkeypatch):
    """
    The cookie still gets cleared — that needs no database and the person asked
    to log out. But the session row is still live, so a copied token starts
    working again as soon as the database does, and reporting {"ok": true}
    would be a lie the caller cannot detect. Raised in review.
    """
    async with client:
        await _login(client)

        def _boom():
            raise RuntimeError("database is down")

        monkeypatch.setattr(db_mod, "AsyncSessionLocal", _boom)
        r = await client.post("/api/auth/logout")

    assert r.status_code == 503
    assert r.json()["ok"] is False
    assert store.sessions[0].revoked_at is None          # it genuinely did not revoke
    assert SESSION_COOKIE_NAME not in r.cookies          # but the cookie is gone


@pytest.mark.asyncio
async def test_a_db_failure_denies_rather_than_admits(client, user, monkeypatch):
    """Fail closed. An unreadable session table must not read as 'no reason to
    stop you'."""
    async with client:
        await _login(client)

        def _boom():
            raise RuntimeError("database is down")

        monkeypatch.setattr(db_mod, "AsyncSessionLocal", _boom)
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_a_failed_last_seen_write_does_not_deny_a_valid_session(client, user, store):
    """
    last_seen_at is bookkeeping. It used to share the fail-closed try block, so
    a failed UPDATE denied a request that had already proved it held a valid
    session — a write problem rejecting a read. Raised in review.
    """
    class _CommitFails(_FakeSession):
        async def commit(self):
            raise RuntimeError("disk full")

    async with client:
        await _login(client)
        store.sessions[0].last_seen_at = None          # force a touch attempt
        db_mod.AsyncSessionLocal = lambda: _CommitFails(store)
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_last_seen_is_not_written_on_every_request(client, user, store):
    """
    This ran an UPDATE plus a commit on every authenticated request, polling
    included. A "last seen" accurate to the minute is not worth that write load.
    """
    async with client:
        await _login(client)
        before = store.commits
        for _ in range(5):
            await client.get("/api/portfolio/positions")
        after = store.commits
    assert after - before <= 1, f"{after - before} commits for 5 reads"


@pytest.mark.asyncio
async def test_everything_stays_open_while_auth_is_disabled(client, user, monkeypatch):
    """
    Default-off has to be genuinely off: existing single-operator installs run
    behind nginx Basic Auth plus the X-Api-Key operator key and must keep
    working untouched after this ships.
    """
    monkeypatch.setattr(settings, "auth_enabled", False)
    async with client:
        r = await client.get("/api/portfolio/positions")
    assert r.status_code == 200
