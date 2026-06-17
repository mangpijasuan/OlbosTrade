"""
Helper for not leaking internal exception detail to API clients.

Many read endpoints historically returned `{"error": str(exc)}`, exposing DB
connection strings, SQLAlchemy internals, and broker errors. `safe_detail`
logs the full exception server-side and returns a generic, client-safe string.
"""

from __future__ import annotations

from app.utils.logger import get_logger

logger = get_logger(__name__)


def safe_detail(exc: Exception, context: str) -> str:
    logger.error("%s: %s", context, exc, exc_info=True)
    return "internal error"
