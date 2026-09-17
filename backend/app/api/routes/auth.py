"""
Login, logout, and "who am I".

There is deliberately no registration route — accounts are provisioned with
scripts/create_user.py. Self-service signup on a platform that connects to
brokers pulls in email verification, bot defence and abuse response, none of
which is worth building before there is a reason to.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.auth_deps import current_user
from app.api.rate_limit import client_ip, login_rate_limit
from app.core.config import settings
from app.services.auth_service import (
    SESSION_COOKIE_NAME, hash_token, new_session_token, normalize_email,
    session_expiry, verify_password,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=1024)


class UserOut(BaseModel):
    id: str
    email: str
    tier: str


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    _rl: None = Depends(login_rate_limit),
) -> dict:
    """
    Exchange credentials for a session cookie.

    Every failure path returns the same 401 and the same message. Saying
    "no such user" versus "wrong password" hands an attacker a free account
    enumeration oracle, and this app's users are, by construction, people with
    brokerage accounts.
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserSession

    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="Authentication is not enabled")

    email = normalize_email(body.email)
    generic = HTTPException(status_code=401, detail="Invalid email or password")

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.email == email).limit(1)
        )).scalar_one_or_none()

        # Verify even when the user is missing, against a throwaway hash, so a
        # nonexistent account does not answer measurably faster than a real one
        # with a wrong password.
        stored = user.password_hash if user else _DUMMY_HASH
        ok = verify_password(body.password, stored)

        if user is None or not ok or not user.is_active:
            logger.warning("Failed login for %s", email or "(blank)")
            raise generic

        token, token_hash = new_session_token()
        db.add(UserSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=session_expiry(settings.auth_session_hours),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
            # Same trust rule as the rate limiter — a session audit row saying
            # every login came from the proxy is worse than useless.
            ip=client_ip(request),
        ))
        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()
        out = UserOut(id=str(user.id), email=user.email, tier=user.tier)

    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.auth_session_hours * 3600,
        httponly=True,                     # not readable by script: XSS cannot lift it
        secure=settings.auth_cookie_secure,
        samesite="lax",                    # survives top-level navigation, blocks cross-site POST
        path="/",
    )
    logger.info("Login: %s", out.email)
    return {"user": out.model_dump()}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    """
    Revoke the session server-side, then clear the cookie.

    Server-side first: clearing only the cookie would leave a token that still
    authenticates anyone who copied it.
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.user import UserSession

    token = request.cookies.get(SESSION_COOKIE_NAME)
    revoked = True
    if token:
        try:
            async with AsyncSessionLocal() as db:
                session = (await db.execute(
                    select(UserSession).where(UserSession.token_hash == hash_token(token)).limit(1)
                )).scalar_one_or_none()
                if session is not None and session.revoked_at is None:
                    session.revoked_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception as exc:
            # The cookie still gets cleared below — the person asked to log out
            # and that part needs no database. But the row is still live, so a
            # token someone copied starts working again the moment the database
            # does, and saying {"ok": true} here would be a lie the caller has
            # no way to detect. Report it instead; the session still dies at
            # expires_at, so the exposure is bounded by AUTH_SESSION_HOURS.
            logger.error("Logout could not revoke server-side: %s", exc)
            revoked = False

    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    if not revoked:
        response.status_code = 503
        return {"ok": False, "detail": "Signed out here, but the session could not "
                                       "be revoked server-side. Retry to be sure."}
    return {"ok": True}


@router.get("/status")
async def status(request: Request) -> dict:
    """
    What the frontend needs at boot, in one public call.

    Public on purpose, and it has to be: with auth DISABLED every route is
    open, so a client asking /me gets a 401 that means "no session" — which is
    indistinguishable from "auth is on and you are logged out". A frontend that
    cannot tell those apart shows a login page on an instance where login
    returns 404. This endpoint answers the actual question.

    It leaks only whether auth is switched on. The user block is filled in from
    the caller's own session, so an unauthenticated request learns nothing
    about who else exists.
    """
    if not settings.auth_enabled:
        return {"auth_enabled": False, "authenticated": False, "user": None}

    # Resolved here rather than read off request.state: this path is in the
    # public allowlist, so require_session returned early without loading it.
    #
    # resolve_session_user, NOT load_session_user: the latter turns an
    # unreadable session store into None, which is right for a protected route
    # (fail closed) and wrong here. A database outage would answer
    # "authenticated: false" with a 200, the client would show the login form,
    # and the operator would retype credentials into a login that cannot
    # succeed either. This is a status probe, so it reports the outage.
    from app.api.auth_deps import SessionLookupError, resolve_session_user

    try:
        user = await resolve_session_user(request)
    except SessionLookupError as exc:
        logger.warning("Auth status could not read the session store: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Cannot determine session state right now",
        ) from exc

    return {
        "auth_enabled": True,
        "authenticated": user is not None,
        "user": {k: user[k] for k in ("id", "email", "tier") if k in user} if user else None,
    }


@router.get("/me")
async def me(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"user": {k: user[k] for k in ("id", "email", "tier") if k in user}}


# A valid Argon2 hash of a value nobody holds. Used so a login attempt for a
# nonexistent account still pays the hashing cost — otherwise response timing
# tells an attacker which emails exist.
from app.services.auth_service import hash_password as _hash_password  # noqa: E402

_DUMMY_HASH = _hash_password("not-a-real-password-timing-equaliser")
