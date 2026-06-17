"""Shared authentication helpers for sensitive API actions."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from app.core.config import settings


def require_admin_api_key(x_api_key: str = Header(default="")) -> None:
    """Require the configured admin API key for state-changing actions."""
    if not settings.secret_key:
        raise HTTPException(status_code=503, detail="SECRET_KEY not configured")
    if not secrets.compare_digest(x_api_key, settings.secret_key):
        raise HTTPException(status_code=403, detail="Invalid API key")
