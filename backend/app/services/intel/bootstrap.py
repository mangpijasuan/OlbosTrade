"""Register the default free/low-cost providers into the shared registry.

Called once at app startup. Adding a premium provider later is a one-line
registration here — business logic is untouched.
"""

from __future__ import annotations

from app.services.intel.provider_registry import registry
from app.services.intel.providers.edgar import EdgarProvider
from app.services.intel.providers.fred import FredProvider
from app.services.intel.providers.rss_news import RssNewsProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_registered = False


def register_default_providers() -> None:
    global _registered
    if _registered:
        return
    registry.register(EdgarProvider())
    registry.register(RssNewsProvider())
    registry.register(FredProvider())  # reports unavailable until FRED_API_KEY set
    _registered = True
    healths = registry.health()
    logger.info("Intel providers registered: %s",
                ", ".join(f"{h.name}={'up' if h.available else 'down'}" for h in healths))
