"""
SQLAlchemy models for user accounts and login sessions.

Identity for the hybrid tenancy model's shared instance. Two deliberate
choices, both explained here because the alternatives look easier:

Sessions are OPAQUE ROWS, not JWTs. A JWT cannot be revoked before it expires
without building a denylist — which is a session table with extra steps. This
platform can reach a broker, so "end that session now" has to actually work:
a compromised laptop, a departing user, a support request. One indexed lookup
per request against a database the app already requires is a cheap price.

Passwords are Argon2id. Not a home-rolled hash, not SHA-anything, and not
bcrypt's 72-byte silent truncation.

Invite-only: there is no public registration route. Accounts are created with
scripts/create_user.py. Self-service signup on a platform that connects to
brokers pulls in email verification, bot defence and abuse response — none of
which is worth building before there is a reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Tiers the landing page advertises. Enforcement of what each one actually
# grants is Phase 3 and deliberately not in this model beyond the label —
# storing a tier is not the same as serving different data for it.
TIER_FREE = "free"
TIER_PRO = "pro"
TIER_ELITE = "elite"
TIERS = (TIER_FREE, TIER_PRO, TIER_ELITE)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Stored lower-cased and matched lower-cased. Case-sensitive emails let the
    # same person register twice and lock themselves out of the first account.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    tier: Mapped[str] = mapped_column(String(20), nullable=False, default=TIER_FREE)

    # Disabling beats deleting: a deleted user frees the email for re-use and
    # orphans any audit trail pointing at the id.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_users_email", "email", unique=True),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # SHA-256 of the token, never the token itself. A leaked database dump
    # should not hand over live sessions, the same reason passwords are hashed.
    # SHA-256 rather than Argon2 here on purpose: this value is 32 bytes of
    # CSPRNG output, not a guessable secret, so it needs no work factor — and
    # it is verified on every single request.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set on logout / revoke. Kept rather than deleted so "when did that session
    # end, and was it a logout or an expiry" stays answerable.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Recorded for the audit trail, not for authentication — both are
    # client-controlled and neither is evidence of anything on its own.
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("idx_user_sessions_token_hash", "token_hash", unique=True),
        Index("idx_user_sessions_user", "user_id"),
        Index("idx_user_sessions_expires", "expires_at"),
    )
