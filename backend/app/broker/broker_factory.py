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
    elif name == "alpaca":
        from app.broker.alpaca_client import AlpacaClient
        _broker_instance = AlpacaClient()
        logger.info("Active broker: Alpaca (base_url=%s)", settings.alpaca_base_url)
    else:
        raise ValueError(
            f"Unknown broker '{name}'. Set BROKER=ibkr or BROKER=alpaca in .env."
        )

    # A read-only deployment wraps the broker rather than trusting every call
    # site to check a flag. Orders are placed from _execute_signal, from
    # position_rotation's entry and close paths, from the manual-close path and
    # from the kill switch's flattening — all of them reach the broker through
    # this factory, so the wrapper is the one place that cannot be bypassed or
    # forgotten by a new call site.
    if not settings.execution_enabled:
        from app.broker.read_only_broker import ReadOnlyBroker
        _broker_instance = ReadOnlyBroker(_broker_instance)
        logger.critical(
            "EXECUTION_ENABLED=false — broker wrapped read-only. This instance "
            "serves signals and research only and cannot place orders."
        )

    return _broker_instance


def reset_broker() -> None:
    """Reset singleton — used in tests only."""
    global _broker_instance
    _broker_instance = None
