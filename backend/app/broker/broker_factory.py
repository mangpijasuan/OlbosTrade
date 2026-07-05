"""
Broker factory — reads settings.broker and returns the correct singleton.
All application code calls get_broker() instead of importing clients directly.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.broker.broker_interface import BrokerInterface

logger = logging.getLogger(__name__)

_broker_instance: Optional[BrokerInterface] = None


def get_broker() -> BrokerInterface:
    """
    Return the active broker singleton.
    Created once at startup; subsequent calls return the same instance.
    Raises ValueError if the broker name in settings is unknown.
    """
    global _broker_instance
    if _broker_instance is not None:
        return _broker_instance

    from app.core.config import settings

    name = settings.broker.lower().strip()

    if name == "ibkr":
        from app.broker.ibkr_client import IBKRClient
        _broker_instance = IBKRClient()
        logger.info("Active broker: IBKR (host=%s port=%s)", settings.ibkr_host, settings.ibkr_port)
    else:
        raise ValueError(
            f"Unknown broker '{name}'. Set BROKER=ibkr in .env."
        )

    return _broker_instance


def reset_broker() -> None:
    """Reset singleton — used in tests only."""
    global _broker_instance
    _broker_instance = None
