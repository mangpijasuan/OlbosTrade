"""
Read-only broker wrapper — makes a deployment structurally incapable of trading.

The hybrid tenancy model runs one SHARED instance serving signals, research and
backtests to many accounts, and a SEPARATE per-tenant stack for anyone who
connects a broker. That only holds if the shared instance cannot place an order
at all — not "is set to Manual", not "has the kill switch armed", both of which
are runtime state a request can change.

Gating `_execute_signal` alone would not be enough, and that was the first
design considered: orders are also placed from position_rotation's entry and
close paths, from trade_desk's manual-close path, and from the kill switch's
own flattening. A check on the signal path would look complete while leaving
three ways through. Every one of them calls `get_broker()`, so the wrapper goes
there — a new call site cannot forget it, and a new broker client cannot miss it.

Closing is deliberately still allowed. Cancelling orders and the kill switch's
flattening only ever REDUCE exposure, and a safety flag that prevents a desk
from closing a position it somehow holds would be a worse failure than the one
this guards against. `EXECUTION_ENABLED=false` is a deployment-time property of
an instance that never opens positions in the first place.
"""

from __future__ import annotations

from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Methods that OPEN or increase exposure. Blocked.
_BLOCKED_METHODS = ("place_order", "place_equity_order")


class ExecutionDisabledError(RuntimeError):
    """Raised when a read-only deployment attempts to place an order."""


class ReadOnlyBroker:
    """
    Proxies every attribute to the real broker, except the order-placing
    methods, which raise. Quotes, chains, positions and account reads all pass
    through untouched — the shared instance still needs live market data to
    produce the signals it exists to serve.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name in _BLOCKED_METHODS:
            async def _refuse(*args: Any, **kwargs: Any) -> Any:
                logger.critical(
                    "ORDER REFUSED: %s() called on a read-only deployment "
                    "(EXECUTION_ENABLED=false). This instance serves signals and "
                    "research only; execution lives in a per-tenant stack.",
                    name,
                )
                raise ExecutionDisabledError(
                    f"{name}() is unavailable: this deployment has EXECUTION_ENABLED=false "
                    "and cannot place orders."
                )
            return _refuse
        return getattr(self._inner, name)

    def __repr__(self) -> str:
        return f"<ReadOnlyBroker wrapping {self._inner!r}>"
