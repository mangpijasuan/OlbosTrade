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
from app.api.rate_limit import rate_limit
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
    _rl: None = Depends(rate_limit),
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
            ip=(request.client.host if request.client else None),
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
            logger.warning("Logout revoke failed: %s", exc)

    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


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
