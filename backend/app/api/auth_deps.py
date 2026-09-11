"""
Session authentication dependency, and the default-deny allowlist.

Default-deny is the whole point of Phase 2. There are 144 route decorators in
this app and 15 of them carried the operator-key dependency; adding a
per-route dependency to the rest guarantees that one gets missed, and the
missed one is found by an incident rather than by a reviewer. So the check is
applied globally and routes opt OUT by path, with a test that enumerates every
registered route and fails CI if a new one is neither protected nor
deliberately allowlisted.

Everything here is inert while settings.auth_enabled is False, which is the
default: an existing single-operator install keeps working on nginx Basic Auth
plus the X-Api-Key operator key exactly as before.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, WebSocketException, status
from starlette.requests import HTTPConnection

from app.core.config import settings
from app.services.auth_service import SESSION_COOKIE_NAME, hash_token, is_session_valid
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Paths reachable without a session. Kept as exact matches and explicit
# prefixes rather than regexes — a permissive pattern here is a hole, and this
# list is the security boundary, so it should be boring to read.
PUBLIC_EXACT = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/health",
    "/health",
    "/",
}
PUBLIC_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/assets",
)


def is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)


async def load_session_user(conn: HTTPConnection) -> Optional[dict]:
    """
    Resolve the caller from the session cookie, or None.

    Takes an HTTPConnection — the shared base of Request and WebSocket — because
    this runs on both, and asking for a Request would make it uncallable on a
    WebSocket route. See require_session.

    Returns a plain dict rather than the ORM object so callers cannot
    accidentally lazy-load or mutate a detached instance.
    """
    token = conn.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserSession

    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(UserSession.token_hash == hash_token(token))
                .limit(1)
            )).first()
            if row is None:
                return None
            session, user = row
            if not is_session_valid(session):
                return None
            if not user.is_active:
                # Disabling an account must end its access immediately, not at
                # the next session expiry.
                return None

            session.last_seen_at = datetime.now(timezone.utc)
            await db.commit()

            return {
                "id": str(user.id),
                "email": user.email,
                "tier": user.tier,
                "session_id": str(session.id),
            }
    except Exception as exc:
        # Fail closed: an unreadable session is not an authenticated one.
        logger.warning("Session lookup failed (treating as unauthenticated): %s", exc)
        return None


async def require_session(conn: HTTPConnection) -> dict:
    """
    Global dependency. Rejects anything without a valid session once
    auth_enabled is on; a no-op otherwise.

    The parameter is an HTTPConnection, NOT a Request, and that is load-bearing.
    As an app-level dependency this is attached to every route including the
    /api/ibkr/live WebSocket, and FastAPI supplies a WebSocket rather than a
    Request in a WebSocket scope. Annotating it Request made the dependency
    uncallable there — a TypeError on every connection attempt, regardless of
    whether auth was enabled, which broke live market data for the frontend
    rather than rejecting anyone. HTTPConnection is the common base of both and
    carries everything used here: cookies, url, state, client.
    """
    if not settings.auth_enabled:
        return {}

    if is_public_path(conn.url.path):
        return {}

    user = await load_session_user(conn)
    if user is None:
        _reject(conn)

    # Downstream handlers read this instead of re-querying.
    conn.state.user = user
    return user


def _reject(conn: HTTPConnection) -> None:
    """
    Refuse the connection in whichever protocol it arrived on.

    An HTTPException raised during a WebSocket handshake is not translated into
    a close frame by Starlette; it surfaces as a server error. The rejection has
    to speak the right protocol or "denied" reads as "broken".
    """
    if conn.scope.get("type") == "websocket":
        # 1008 = policy violation, the conventional close code for auth failure.
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION,
                                 reason="Authentication required")
    raise HTTPException(status_code=401, detail="Authentication required")


def current_user(conn: HTTPConnection) -> dict:
    """Read the user resolved by require_session. {} when auth is disabled."""
    return getattr(conn.state, "user", {}) or {}
