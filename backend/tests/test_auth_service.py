"""Auth service: password hashing and session validity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.auth_service import (
    hash_password, hash_token, is_session_valid, new_session_token,
    normalize_email, session_expiry, verify_password,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _session(**over):
    base = dict(revoked_at=None, expires_at=NOW + timedelta(hours=1))
    base.update(over)
    return SimpleNamespace(**base)


# ── passwords ────────────────────────────────────────────────────────────────

def test_hash_is_argon2id_and_verifies():
    h = hash_password("a sufficiently long password")
    assert h.startswith("$argon2id$")
    assert verify_password("a sufficiently long password", h) is True


def test_wrong_password_rejected():
    assert verify_password("nope", hash_password("real password here")) is False


def test_same_password_hashes_differently():
    """Per-hash salt: identical passwords must not produce identical hashes,
    or the column leaks which users share a password."""
    p = "identical password"
    assert hash_password(p) != hash_password(p)


def test_malformed_stored_hash_fails_closed():
    """
    A truncated or corrupt hash column must return False, not raise. Raising
    would surface a traceback from the login route that distinguishes "bad
    stored hash" from "wrong password" to whoever is probing.
    """
    assert verify_password("anything", "") is False
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "$argon2id$truncated") is False


def test_long_password_is_not_silently_truncated():
    """bcrypt silently ignores bytes past 72; Argon2 does not. Two passwords
    sharing a 72-byte prefix must not be interchangeable."""
    a = "x" * 72 + "AAAA"
    b = "x" * 72 + "BBBB"
    assert verify_password(b, hash_password(a)) is False


# ── session tokens ───────────────────────────────────────────────────────────

def test_tokens_are_unique_and_hash_stably():
    t1, h1 = new_session_token()
    t2, h2 = new_session_token()
    assert t1 != t2 and h1 != h2
    assert hash_token(t1) == h1
    assert len(h1) == 64          # sha256 hex


def test_plaintext_token_is_not_recoverable_from_the_hash():
    t, h = new_session_token()
    assert t not in h


# ── session validity ─────────────────────────────────────────────────────────

def test_valid_session():
    assert is_session_valid(_session(), now=NOW) is True


def test_missing_session_is_invalid():
    assert is_session_valid(None, now=NOW) is False


def test_revoked_session_is_invalid_even_before_expiry():
    """Logout has to mean logged out — the whole reason these are DB rows
    rather than JWTs."""
    s = _session(revoked_at=NOW - timedelta(minutes=1))
    assert is_session_valid(s, now=NOW) is False


def test_expired_session_is_invalid():
    assert is_session_valid(_session(expires_at=NOW - timedelta(seconds=1)), now=NOW) is False


def test_session_expiring_exactly_now_is_invalid():
    """Boundary: expires_at == now must not still be valid."""
    assert is_session_valid(_session(expires_at=NOW), now=NOW) is False


def test_naive_expiry_is_treated_as_utc_not_crashed_on():
    naive = (NOW + timedelta(hours=1)).replace(tzinfo=None)
    assert is_session_valid(_session(expires_at=naive), now=NOW) is True


def test_null_expiry_is_invalid():
    """A row with no expiry is malformed; it must not read as a session that
    never expires."""
    assert is_session_valid(_session(expires_at=None), now=NOW) is False


def test_session_expiry_is_in_the_future():
    assert session_expiry(12) > datetime.now(timezone.utc)


# ── configuration that would lock everyone out ───────────────────────────────

@pytest.mark.parametrize("hours", [0, -1, -12])
def test_non_positive_session_hours_is_refused_at_startup(hours):
    """
    AUTH_SESSION_HOURS=0 was accepted, and then login returned 200 while
    storing an already-expired session and sending Max-Age=0 — the browser
    dropped the cookie and every account was locked out, with no error to
    explain it. Refusing to start is the kinder failure. Raised in review.
    """
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(auth_session_hours=hours)


def test_a_normal_session_length_is_accepted():
    from app.core.config import Settings
    assert Settings(auth_session_hours=12).auth_session_hours == 12


# ── email normalisation ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("  USER@Example.COM ", "user@example.com"),
    ("user@example.com", "user@example.com"),
    ("", ""),
])
def test_email_normalisation(raw, expected):
    """Case-sensitive emails let one person register twice and lock themselves
    out of the first account."""
    assert normalize_email(raw) == expected
