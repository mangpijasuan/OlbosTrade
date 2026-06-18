"""
MODULE 3 — Multi-Leg Strategy Structure.

This is an EXTENSION of strategy_engine.py, not a replacement.

strategy_engine.py:          Strategy signal generation (when to enter/exit).
MultiLegStrategy (here):     Order construction (what the order IS — legs, premiums,
                             aggregate Greeks, max profit/loss calculation).

The existing SpreadOrder in broker_interface.py handles wire-format order submission.
MultiLegStrategy is the in-memory analytical representation BEFORE submission.

Relationship:
    strategy_engine.py generates a Signal
    → MultiLegStrategy.from_signal() constructs the order structure
    → RiskManager + ExecutionDispatcher (module 4) validate and submit
    → broker_interface.SpreadOrder is the wire format sent to the active broker
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from app.broker.contract import EnrichedContract

logger = logging.getLogger(__name__)


class LegAction(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


@dataclass
class StrategyLeg:
    """
    One leg of a multi-leg options strategy.

    quantity is always positive — direction is captured by action.
    net_premium = gross_fill * quantity * 100 * sign(action)
    """
    contract:  EnrichedContract
    action:    LegAction
    quantity:  int                          # always positive
    fill_price: Optional[float] = None      # set after fill

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")

    @property
    def sign(self) -> int:
        """
        +1 for SELL (credit received), -1 for BUY (debit paid).
        From the seller's perspective — matches how options P&L is typically framed.
        """
        return 1 if self.action == LegAction.SELL else -1

    @property
    def net_premium_at_mid(self) -> float:
        """
        Net premium contribution of this leg at mid price.
        Positive = credit received. Negative = debit paid.
        Each contract covers 100 shares.
        """
        return self.contract.mid_price * self.quantity * 100 * self.sign

    @property
    def leg_delta(self) -> float:
        """Signed position delta. None if contract not enriched."""
        if self.contract.delta is None:
            return 0.0
        return self.contract.delta * self.quantity * self.sign * -1
        # Note: SELL flips delta sign (short position has opposite delta exposure)

    @property
    def leg_gamma(self) -> float:
        if self.contract.gamma is None:
            return 0.0
        return self.contract.gamma * self.quantity * self.sign * -1

    @property
    def leg_vega(self) -> float:
        if self.contract.vega is None:
            return 0.0
        return self.contract.vega * self.quantity * self.sign * -1

    @property
    def leg_theta(self) -> float:
        if self.contract.theta is None:
            return 0.0
        # Short options have POSITIVE theta (time works in seller's favor)
        return self.contract.theta * self.quantity * self.sign * -1

    def __repr__(self) -> str:
        return (
            f"StrategyLeg({self.action.value} {self.quantity}x "
            f"{self.contract.option_type.upper()} "
            f"${self.contract.strike_price:.0f} "
            f"exp={self.contract.expiration_date} "
            f"mid={self.contract.mid_price:.2f})"
        )


@dataclass
class MultiLegStrategy:
    """
    Complete in-memory representation of a multi-leg options strategy.

    Supports any combination of legs (spreads, condors, strangles, etc.).
    Computes net premium and aggregate Greeks across all legs.

    Thread-safe: fields set at construction; aggregate properties are
    computed from immutable leg data.
    """

    strategy_name: str
    underlying:    str
    legs:          list[StrategyLeg]
    order_id:      str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at:    datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("MultiLegStrategy requires at least one leg")
        if not self.underlying:
            raise ValueError("underlying ticker is required")

    # ── Net premium ───────────────────────────────────────────────────────────

    @property
    def net_premium(self) -> float:
        """
        Total net premium across all legs at mid prices.

        Positive = net credit (money received).
        Negative = net debit (money paid).
        """
        return sum(leg.net_premium_at_mid for leg in self.legs)

    @property
    def is_credit(self) -> bool:
        return self.net_premium > 0

    @property
    def is_debit(self) -> bool:
        return self.net_premium < 0

    # ── Aggregate Greeks ──────────────────────────────────────────────────────

    @property
    def net_delta(self) -> float:
        """
        Aggregate position delta.
        Measures directional exposure: +0.30 means you gain if underlying rises.
        """
        return sum(leg.leg_delta for leg in self.legs)

    @property
    def net_gamma(self) -> float:
        """
        Aggregate position gamma.
        Negative gamma (short gamma) = position loses value as underlying moves.
        """
        return sum(leg.leg_gamma for leg in self.legs)

    @property
    def net_vega(self) -> float:
        """
        Aggregate position vega.
        Negative vega = position profits from IV decrease (typical for credit spreads).
        """
        return sum(leg.leg_vega for leg in self.legs)

    @property
    def net_theta(self) -> float:
        """
        Aggregate daily theta.
        Positive theta = position gains value each day (good for credit sellers).
        """
        return sum(leg.leg_theta for leg in self.legs)

    # ── Risk profile ──────────────────────────────────────────────────────────

    @property
    def max_profit(self) -> Optional[float]:
        """
        Max profit for defined-risk spreads.
        For credit spreads: equals net premium received.
        Returns None for undefined-risk strategies.
        """
        if self.is_credit:
            return abs(self.net_premium)
        return None  # Debit spreads: max profit requires knowing spread width

    @property
    def spread_width_dollars(self) -> Optional[float]:
        """
        Width of the spread in dollars per contract.
        Calculated as the difference between the two strikes for 2-leg spreads.
        For Iron Condors, returns the width of the wider wing.
        """
        strikes = sorted(set(leg.contract.strike_price for leg in self.legs))
        if len(strikes) < 2:
            return None
        # For spreads with 2 distinct strikes
        if len(strikes) == 2:
            return (strikes[1] - strikes[0]) * 100
        # For Iron Condors (4 strikes) — return width of each wing
        if len(strikes) == 4:
            put_width  = (strikes[1] - strikes[0]) * 100
            call_width = (strikes[3] - strikes[2]) * 100
            return max(put_width, call_width)
        return None

    @property
    def max_loss(self) -> Optional[float]:
        """
        Max loss for defined-risk credit spreads.
        = (spread_width - net_credit) per contract.
        Returns None for undefined-risk strategies.
        """
        if not self.is_credit or self.spread_width_dollars is None:
            return None
        return self.spread_width_dollars - abs(self.net_premium)

    @property
    def risk_reward_ratio(self) -> Optional[float]:
        """
        Net credit / max loss.
        Higher is better for credit spread traders.
        Industry target: > 0.25 (25c credit for $1 of max risk).
        """
        if self.max_profit is None or self.max_loss is None or self.max_loss <= 0:
            return None
        return round(self.max_profit / self.max_loss, 4)

    @property
    def breakeven_prices(self) -> list[float]:
        """
        Breakeven prices at expiration for 2-leg credit spreads.
        Returns list because Iron Condors have two breakevens.
        """
        sorted_legs = sorted(self.legs, key=lambda l: l.contract.strike_price)
        credit_per_share = abs(self.net_premium) / 100  # per share (not per contract)

        breakevens = []
        put_legs  = [l for l in sorted_legs if l.contract.option_type == "put"]
        call_legs = [l for l in sorted_legs if l.contract.option_type == "call"]

        if put_legs:
            # Bull put spread: breakeven = short put strike - net credit
            short_put = max(put_legs, key=lambda l: l.contract.strike_price)
            if short_put.action == LegAction.SELL:
                breakevens.append(short_put.contract.strike_price - credit_per_share)

        if call_legs:
            # Bear call spread: breakeven = short call strike + net credit
            short_call = min(call_legs, key=lambda l: l.contract.strike_price)
            if short_call.action == LegAction.SELL:
                breakevens.append(short_call.contract.strike_price + credit_per_share)

        return breakevens

    # ── Conversion to wire format ─────────────────────────────────────────────

    def to_spread_order(
        self,
        order_type: Literal["LMT", "MKT"] = "LMT",
        time_in_force: Literal["DAY", "GTC"] = "DAY",
    ):
        """
        Convert to broker_interface.SpreadOrder for submission via BrokerInterface.
        This is the handoff point between analytics and execution.
        """
        from decimal import Decimal
        from app.broker.broker_interface import SpreadLeg, SpreadOrder

        wire_legs = [
            SpreadLeg(
                symbol=leg.contract.underlying_ticker
                       + leg.contract.expiration_date.strftime("%y%m%d")
                       + leg.contract.option_type[0].upper()
                       + f"{int(leg.contract.strike_price * 1000):08d}",
                strike=Decimal(str(leg.contract.strike_price)),
                expiration=leg.contract.expiration_date,
                option_type=leg.contract.option_type,
                action=leg.action.value,
                quantity=leg.quantity,
            )
            for leg in self.legs
        ]

        return SpreadOrder(
            strategy=self.strategy_name,
            underlying=self.underlying,
            legs=wire_legs,
            limit_price=Decimal(str(round(self.net_premium / 100, 4))),
            order_type=order_type,
            time_in_force=time_in_force,
            client_order_id=self.order_id,
        )

    def summary(self) -> dict:
        """Human-readable summary dict for logging and API responses."""
        return {
            "order_id":         self.order_id,
            "strategy_name":    self.strategy_name,
            "underlying":       self.underlying,
            "legs":             [repr(l) for l in self.legs],
            "net_premium":      round(self.net_premium, 2),
            "type":             "credit" if self.is_credit else "debit",
            "max_profit":       round(self.max_profit, 2) if self.max_profit else None,
            "max_loss":         round(self.max_loss, 2) if self.max_loss else None,
            "risk_reward":      self.risk_reward_ratio,
            "breakevens":       self.breakeven_prices,
            "net_delta":        round(self.net_delta, 4),
            "net_gamma":        round(self.net_gamma, 6),
            "net_vega":         round(self.net_vega, 4),
            "net_theta":        round(self.net_theta, 4),
            "spread_width":     self.spread_width_dollars,
        }

    def __repr__(self) -> str:
        direction = "CR" if self.is_credit else "DR"
        return (
            f"MultiLegStrategy({self.strategy_name} {self.underlying} "
            f"{direction} ${abs(self.net_premium):.2f} "
            f"Δ={self.net_delta:.3f} legs={len(self.legs)})"
        )
