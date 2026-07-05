"""
CSP eligibility gate — the single place that decides whether a cash-secured put
candidate is eligible, caution, or blocked, and in which execution modes.

This enforces the product principle "never hide blocked actions — explain why
and what would change it." Every block carries a human reason and, where
possible, an unblock_condition.

The gate is PURE: it consumes already-evaluated signals (kill switch state,
guardrail status, portfolio overlap, assignment/event risk) and returns a
verdict. The route layer wires in the live GuardrailEngine, KillSwitch, and
RiskManager. This separation keeps the safety logic unit-testable and keeps
WQS (which ranks *quality*) firmly separate from eligibility (which enforces
*safety*).

Mode policy:
  * manual     — always allowed (human places the order).
  * copilot    — allowed for eligible and caution (human approves each).
  * autopilot  — allowed only for fully eligible, no caution flags.
  * blocked    — no modes; hard stop regardless of mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EligibilityStatus = Literal["eligible", "caution", "blocked"]
Mode = Literal["manual", "copilot", "autopilot"]


@dataclass
class GateInputs:
    """Pre-computed signals for one candidate. All booleans/levels come from the
    live systems (kill switch, guardrails, risk manager) or the risk services."""

    kill_switch_engaged: bool
    guardrails_allowed: bool
    guardrails_reason: str | None          # populated when guardrails_allowed is False

    portfolio_overlap_pct: float           # existing exposure to this underlying
    max_overlap_pct: float                 # profile/config limit

    assignment_level: Literal["low", "moderate", "high"]
    earnings_level: Literal["low", "moderate", "high"] | None
    macro_level: Literal["low", "moderate", "high"]

    buying_power: float
    collateral_required: float


@dataclass
class Eligibility:
    status: EligibilityStatus
    blocked_reasons: list[str] = field(default_factory=list)
    caution_reasons: list[str] = field(default_factory=list)
    unblock_condition: str | None = None
    modes_allowed: list[Mode] = field(default_factory=list)


def evaluate_eligibility(inp: GateInputs) -> Eligibility:
    blocked: list[str] = []
    unblock: str | None = None

    # ── Hard blocks (any one blocks the trade in all modes) ──────────────────
    if inp.kill_switch_engaged:
        blocked.append("Kill switch engaged")
        unblock = unblock or "Reset the kill switch"

    if not inp.guardrails_allowed:
        blocked.append(inp.guardrails_reason or "Guardrails blocking new trades")
        unblock = unblock or "Clear the active guardrail condition"

    if inp.collateral_required > inp.buying_power:
        blocked.append("Insufficient buying power for collateral")
        unblock = unblock or (
            f"Free up ${inp.collateral_required - inp.buying_power:,.0f} in buying power"
        )

    if inp.portfolio_overlap_pct > inp.max_overlap_pct:
        blocked.append(
            f"Single-symbol exposure too high "
            f"({inp.portfolio_overlap_pct:.0f}% > {inp.max_overlap_pct:.0f}% limit)"
        )
        unblock = unblock or f"Reduce exposure to below {inp.max_overlap_pct:.0f}%"

    if blocked:
        return Eligibility(
            status="blocked",
            blocked_reasons=blocked,
            unblock_condition=unblock,
            modes_allowed=[],
        )

    # ── Caution flags (allowed, but downgrade autopilot eligibility) ─────────
    caution: list[str] = []
    if inp.assignment_level == "high":
        caution.append("Elevated assignment risk")
    if inp.earnings_level in ("moderate", "high"):
        caution.append("Earnings before expiry")
    if inp.macro_level in ("moderate", "high"):
        caution.append("High-impact macro event before expiry")

    if caution:
        return Eligibility(
            status="caution",
            caution_reasons=caution,
            modes_allowed=["manual", "copilot"],  # autopilot excluded
        )

    return Eligibility(
        status="eligible",
        modes_allowed=["manual", "copilot", "autopilot"],
    )
