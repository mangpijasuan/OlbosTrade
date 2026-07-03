"""
Assignment-risk calculator for cash-secured puts.

Estimates the likelihood of being assigned (put finishing ITM) from three
observable signals, without needing a full pricing model:

  * delta — the market's own rough probability the option finishes ITM.
  * cushion — how far out-of-the-money the strike sits, in percent of spot.
  * dte — less time to expiry with an ITM-leaning strike raises pin risk.

Returns the RiskFlag shape (level / label / detail) used across the CSP
screener. This is an ESTIMATE for ranking and disclosure — it does not gate
trades; the eligibility gate does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RiskLevel = Literal["low", "moderate", "high"]


@dataclass
class RiskFlag:
    level: RiskLevel
    label: str
    detail: str


@dataclass
class AssignmentInputs:
    stock_price: float
    put_strike: float
    delta: float          # absolute value, 0–1
    dte: int


def _cushion_pct(inp: AssignmentInputs) -> float:
    """Percent the strike sits below spot. Negative if strike is ITM."""
    if inp.stock_price <= 0:
        return 0.0
    return (inp.stock_price - inp.put_strike) / inp.stock_price * 100.0


def assess_assignment_risk(inp: AssignmentInputs) -> RiskFlag:
    cushion = _cushion_pct(inp)

    # ITM already — assignment is likely.
    if cushion <= 0:
        return RiskFlag(
            "high", "Assign high",
            f"Strike is in-the-money ({cushion:.1f}% cushion) — assignment likely",
        )

    # Delta is the primary probability signal; cushion and DTE adjust it.
    if inp.delta >= 0.35 or cushion < 2.0:
        return RiskFlag(
            "high", "Assign high",
            f"Δ {inp.delta:.2f}, {cushion:.1f}% OTM, {inp.dte}d — elevated pin risk",
        )
    if inp.delta >= 0.25 or cushion < 5.0:
        return RiskFlag(
            "moderate", "Assign moderate",
            f"Δ {inp.delta:.2f}, {cushion:.1f}% OTM, {inp.dte}d",
        )
    return RiskFlag(
        "low", "Assign low",
        f"Δ {inp.delta:.2f}, {cushion:.1f}% OTM, {inp.dte}d — comfortable cushion",
    )
