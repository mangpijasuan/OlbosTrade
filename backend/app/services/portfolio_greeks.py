"""
Portfolio Greeks Tracker — tracks combined delta/vega/theta across ALL positions
(equity + options) as a single unified exposure view.

Equity: delta = qty (long) or -qty (short), vega=0, theta=0.
Options: delta/vega/theta from broker Greeks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.risk_manager import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class PositionGreeks:
    symbol: str
    delta: float
    vega: float
    theta: float
    quantity: int
    instrument_type: str  # "equity" | "option"


class PortfolioGreeksTracker:
    """
    Maintains net delta/vega/theta across the entire portfolio.
    Thread-safe via Python's GIL for single-process usage.

    Limits are imported from RiskManager rather than restated here. They used
    to be copied (0.30 / 0.15 written out in both modules), which meant raising
    a limit in the module that actually gates trades left this module quietly
    reporting against the old one. One source of truth; RiskManager owns it.
    """

    MAX_DELTA = RiskManager.MAX_PORTFOLIO_DELTA
    MAX_VEGA = RiskManager.MAX_VEGA_EXPOSURE

    # A "flat enough" band for reporting, NOT a risk limit — it is deliberately
    # tighter than MAX_DELTA. It previously appeared as a bare 0.15 inline,
    # which read as if it were tied to the vega limit; the two are equal today
    # only by coincidence, and nothing should keep them in step.
    DELTA_NEUTRAL_BAND = 0.15

    def __init__(self) -> None:
        self._positions: dict[str, PositionGreeks] = {}

    def add_equity_position(self, ticker: str, qty: int, side: str) -> None:
        """
        Add or update an equity position.
        side: "long" or "short"
        Equity delta = +qty (long) or -qty (short).
        """
        signed_qty = qty if side.lower() == "long" else -qty
        self._positions[ticker] = PositionGreeks(
            symbol=ticker,
            delta=float(signed_qty),
            vega=0.0,
            theta=0.0,
            quantity=signed_qty,
            instrument_type="equity",
        )
        logger.debug("PortfolioGreeks: added equity %s qty=%d delta=%+.0f", ticker, signed_qty, signed_qty)

    def add_options_position(
        self,
        symbol: str,
        delta: float,
        vega: float,
        theta: float,
        qty: int,
        side: str = "long",
    ) -> None:
        """Add or update an options position with broker-provided Greeks."""
        self._positions[symbol] = PositionGreeks(
            symbol=symbol,
            delta=delta * qty,
            vega=vega * qty,
            theta=theta * qty,
            quantity=qty,
            instrument_type="option",
        )
        logger.debug(
            "PortfolioGreeks: added option %s qty=%d delta=%+.4f vega=%+.4f theta=%+.4f",
            symbol, qty, delta * qty, vega * qty, theta * qty,
        )

    def remove_position(self, symbol: str) -> None:
        """Remove a position from the tracker."""
        if symbol in self._positions:
            del self._positions[symbol]
            logger.debug("PortfolioGreeks: removed %s", symbol)

    def clear(self) -> None:
        """Clear all positions — call on account reset."""
        self._positions.clear()

    @property
    def position_count(self) -> int:
        return len(self._positions)

    @property
    def equity_position_count(self) -> int:
        return sum(1 for p in self._positions.values() if p.instrument_type == "equity")

    @property
    def options_position_count(self) -> int:
        return sum(1 for p in self._positions.values() if p.instrument_type == "option")

    def net_delta(self) -> float:
        """Total directional exposure (normalised as fraction for options; raw for equities)."""
        # For equities: sum of shares is NOT comparable to normalized options delta.
        # We treat equity delta separately by normalising by 100 (1 options contract = 100 shares).
        total = 0.0
        for p in self._positions.values():
            if p.instrument_type == "equity":
                total += p.delta / 100.0   # normalise to options-equivalent
            else:
                total += p.delta
        return round(total, 6)

    def net_vega(self) -> float:
        """Total vega exposure across options positions."""
        return round(sum(p.vega for p in self._positions.values()), 6)

    def net_theta(self) -> float:
        """Daily time decay income/cost. Positive = net theta seller."""
        return round(sum(p.theta for p in self._positions.values()), 6)

    def is_delta_neutral(self) -> bool:
        """True when |net_delta| is inside the neutrality band."""
        return abs(self.net_delta()) < self.DELTA_NEUTRAL_BAND

    def needs_hedge(self) -> bool:
        """True when |net_delta| exceeds RiskManager's delta limit."""
        return abs(self.net_delta()) > self.MAX_DELTA

    def vega_at_limit(self) -> bool:
        """True when |net_vega| exceeds RiskManager's vega limit."""
        return abs(self.net_vega()) > self.MAX_VEGA

    def snapshot(self) -> dict:
        """Return a serialisable snapshot for logging / DB storage."""
        return {
            "net_delta":               self.net_delta(),
            "net_vega":                self.net_vega(),
            "net_theta":               self.net_theta(),
            "equity_position_count":   self.equity_position_count,
            "options_position_count":  self.options_position_count,
            "total_position_count":    self.position_count,
            "is_delta_neutral":        self.is_delta_neutral(),
            "needs_hedge":             self.needs_hedge(),
        }
