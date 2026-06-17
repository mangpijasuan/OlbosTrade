"""
Shared API security dependencies.

`require_api_key` is a FastAPI dependency that protects state-changing /
trade-execution endpoints. It checks the `X-Api-Key` header against
`settings.secret_key`. If no secret is configured it fails CLOSED (503) so a
misconfigured deploy cannot leave order endpoints wide open.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from app.core.config import settings


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.secret_key:
        # Fail closed — never allow execution endpoints without a configured key.
        raise HTTPException(status_code=503, detail="SECRET_KEY not configured")
    if x_api_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
