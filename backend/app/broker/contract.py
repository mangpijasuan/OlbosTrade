"""
MODULE 1 — Option Contract Data Model.

This is an EXTENSION of broker_interface.OptionContract, not a replacement.
OptionContract in broker_interface.py uses Pydantic for API serialization.
This EnrichedContract adds computed properties (mid_price, spread_width)
and analytics integration without touching the wire-format model.

Design decision: we wrap rather than inherit Pydantic models to keep
the serialization boundary clean. EnrichedContract is used internally
by the analytics engine and risk manager only.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class EnrichedContract:
    """
    In-memory option contract with computed analytics properties.

    Wraps the raw market data fields and provides:
      - mid_price:    (bid + ask) / 2
      - spread_width: ask - bid (absolute)
      - spread_pct:   spread as % of mid — the key liquidity signal
      - tte_years:    time to expiration in years (safe for T=0)

    Thread-safe: all fields are set at construction; computed properties
    are pure functions of those fields — no mutable state.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    underlying_ticker: str
    strike_price: float
    expiration_date: date
    option_type: Literal["call", "put"]

    # ── Market data ───────────────────────────────────────────────────────────
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int

    # ── Optional enrichment (populated by AnalyticsEngine) ───────────────────
    implied_vol: Optional[float] = field(default=None)
    delta:       Optional[float] = field(default=None)
    gamma:       Optional[float] = field(default=None)
    vega:        Optional[float] = field(default=None)
    theta:       Optional[float] = field(default=None)
    rho:         Optional[float] = field(default=None)

    # ── Metadata ──────────────────────────────────────────────────────────────
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.bid < 0:
            raise ValueError(f"bid cannot be negative: {self.bid}")
        if self.ask < self.bid:
            raise ValueError(
                f"Ask ({self.ask}) must be >= bid ({self.bid})"
            )
        if self.strike_price <= 0:
            raise ValueError(f"strike_price must be positive: {self.strike_price}")

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def mid_price(self) -> float:
        """
        Theoretical fill reference price.
        Use this for analytics — never use bid or ask directly for pricing.
        """
        return (self.bid + self.ask) / 2.0

    @property
    def spread_width(self) -> float:
        """Absolute bid-ask spread in dollars."""
        return self.ask - self.bid

    @property
    def spread_pct(self) -> float:
        """
        Spread as a percentage of mid price.
        This is the primary liquidity quality metric.

        < 5%:  excellent (SPY, QQQ liquid strikes)
        5-15%: acceptable
        > 15%: illiquid — risk manager should warn or reject
        > 50%: danger zone — market maker is not committed
        """
        if self.mid_price <= 0:
            return float("inf")
        return (self.spread_width / self.mid_price) * 100.0

    @property
    def tte_years(self) -> float:
        """
        Time to expiration in years. Returns MIN_TTE floor for 0DTE
        so downstream Black-Scholes calculations never divide by zero.
        """
        today = datetime.now(timezone.utc).date()
        calendar_days = (self.expiration_date - today).days
        # Floor at MIN_T_YEARS (1 trading minute = 1/(365*390)) to handle 0DTE safely
        raw_years = max(calendar_days, 0) / 365.0
        return max(raw_years, 1.0 / (365 * 390))

    @property
    def is_0dte(self) -> bool:
        """True if expiration is today."""
        return self.expiration_date == datetime.now(timezone.utc).date()

    @property
    def is_itm(self, underlying_price: Optional[float] = None) -> bool:
        """
        Convenience check. Requires underlying_price to be meaningful.
        Without underlying_price, returns False (cannot determine).
        """
        return False  # Populated externally when underlying price is known

    def itm(self, underlying_price: float) -> bool:
        """Check if this contract is in the money given an underlying price."""
        if self.option_type == "call":
            return underlying_price > self.strike_price
        return underlying_price < self.strike_price

    def __repr__(self) -> str:
        return (
            f"EnrichedContract({self.underlying_ticker} "
            f"{self.expiration_date} "
            f"{self.option_type.upper()} "
            f"${self.strike_price:.2f} "
            f"bid={self.bid:.2f} ask={self.ask:.2f} "
            f"mid={self.mid_price:.2f} "
            f"spread={self.spread_pct:.1f}%)"
        )
