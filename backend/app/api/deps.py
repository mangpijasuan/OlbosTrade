"""Shared FastAPI dependencies for operator-sensitive routes."""
from __future__ import annotations

from fastapi import Header, HTTPException

from app.core.config import settings


def require_api_key(x_api_key: str = Header(default="", alias="X-Api-Key")) -> None:
    """
    Require X-Api-Key matching SECRET_KEY when SECRET_KEY is configured.

    When SECRET_KEY is empty (typical local paper), the check is skipped so the
    SPA keeps working behind nginx Basic Auth alone. Production must set
    SECRET_KEY — then the browser sends a session-entered key (never baked into
    the bundle).
    """
    if not settings.secret_key:
        return
    if x_api_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


def require_api_key_configured(x_api_key: str = Header(default="", alias="X-Api-Key")) -> None:
    """
    Strict: SECRET_KEY must be set and X-Api-Key must match.
    Used for programmatic kill-switch trigger (not the UI engage path).
    """
    if not settings.secret_key:
        raise HTTPException(status_code=503, detail="SECRET_KEY not configured")
    if x_api_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
