"""
Orderflow engine — bid/ask imbalance score from broker's latest quote.
Scores in [-1.0, +1.0]: positive = bullish pressure, negative = bearish.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.broker.broker_interface import BrokerInterface

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, float]] = {}  # ticker -> (score, timestamp)
_CACHE_TTL = 45.0  # seconds


async def get_orderflow_score(ticker: str, broker: "BrokerInterface") -> float:
    """
    Fetch the latest quote from broker and compute bid/ask imbalance.

    Returns a float in [-1.0, +1.0]:
      +1.0 = all bids (strong buy pressure)
      -1.0 = all asks (strong sell pressure)
       0.0 = balanced or wide spread penalty applied

    Falls back to 0.0 on any error (never blocks a trade).
    """
    now = time.monotonic()
    cached = _CACHE.get(ticker)
    if cached is not None:
        score, ts = cached
        if now - ts < _CACHE_TTL:
            return score

    try:
        quote = await broker.get_latest_quote(ticker)

        bid_sz = float(quote.bid_size)
        ask_sz = float(quote.ask_size)
        total  = bid_sz + ask_sz

        if total == 0:
            _CACHE[ticker] = (0.0, now)
            return 0.0

        raw_score = (bid_sz - ask_sz) / total

        # Spread penalty: wide spread → signal is less reliable
        bid_p = float(quote.bid_price)
        ask_p = float(quote.ask_price)
        mid   = (bid_p + ask_p) / 2.0 if (bid_p + ask_p) > 0 else 1.0
        spread_pct = (ask_p - bid_p) / mid if mid > 0 else 0

        if spread_pct > 0.01:  # > 1% spread → reduce weight
            penalty = min(spread_pct / 0.01, 3.0)
            raw_score = raw_score / penalty

        score = max(-1.0, min(1.0, raw_score))
        _CACHE[ticker] = (score, now)
        return round(score, 4)

    except NotImplementedError:
        # Broker doesn't support equity quotes (shouldn't happen normally)
        logger.debug("Orderflow: broker does not support get_latest_quote for %s", ticker)
        _CACHE[ticker] = (0.0, now)
        return 0.0
    except Exception as exc:
        logger.warning("Orderflow score failed for %s: %s — using 0.0", ticker, exc)
        _CACHE[ticker] = (0.0, now)
        return 0.0
