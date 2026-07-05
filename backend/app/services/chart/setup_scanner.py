"""
Setup Readiness Scanner — Module 6.

Ranks symbols by trade-confirmation score and attaches eligibility. Blocked
candidates are NEVER hidden — the reason and the condition needed for
eligibility are always shown (mirrors the CSP eligibility gate philosophy).

Pure ranking + eligibility; the route assembles the per-symbol evidence. This
is research/readiness only — it produces no orders and bypasses no gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

EligibilityStatus = Literal["eligible", "caution", "blocked"]
Mode = Literal["manual", "copilot", "autopilot"]


@dataclass
class SetupCandidate:
    symbol: str
    bias: str
    confirmation_score: int
    structure_state: str
    timeframe_alignment: str
    macro_risk: str
    portfolio_overlap_pct: Optional[float]
    max_overlap_pct: float = 25.0
    min_confirmation: int = 60
    strategy_fit: list[str] = field(default_factory=list)


@dataclass
class SetupResult:
    symbol: str
    bias: str
    confirmation_score: int
    structure_state: str
    timeframe_alignment: str
    macro_risk: str
    portfolio_overlap_pct: Optional[float]
    strategy_fit: list[str]
    status: EligibilityStatus
    blocked_reasons: list[str]
    unblock_condition: Optional[str]
    modes_allowed: list[Mode]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "bias": self.bias,
            "confirmation_score": self.confirmation_score,
            "structure_state": self.structure_state,
            "timeframe_alignment": self.timeframe_alignment,
            "macro_risk": self.macro_risk,
            "portfolio_overlap_pct": self.portfolio_overlap_pct,
            "strategy_fit": self.strategy_fit,
            "status": self.status,
            "blocked_reasons": self.blocked_reasons,
            "unblock_condition": self.unblock_condition,
            "modes_allowed": self.modes_allowed,
        }


def _eligibility(c: SetupCandidate) -> SetupResult:
    blocked: list[str] = []
    unblock: Optional[str] = None

    # Hard blocks (portfolio concentration; readiness-level only — the real
    # order-path gates still apply downstream, this never authorizes a trade).
    if c.portfolio_overlap_pct is not None and c.portfolio_overlap_pct > c.max_overlap_pct:
        blocked.append(
            f"Portfolio overlap {c.portfolio_overlap_pct:.0f}% exceeds "
            f"{c.max_overlap_pct:.0f}% concentration limit"
        )
        unblock = f"Reduce exposure below {c.max_overlap_pct:.0f}%"

    if c.confirmation_score < c.min_confirmation:
        blocked.append(f"Confirmation score {c.confirmation_score} below {c.min_confirmation} threshold")
        unblock = unblock or f"Wait for confirmation score >= {c.min_confirmation}"

    if c.bias == "neutral":
        blocked.append("No directional bias yet")
        unblock = unblock or "Wait for timeframe alignment"

    if blocked:
        return _mk(c, "blocked", blocked, unblock, [])

    # Caution: elevated macro risk allowed but excludes autopilot.
    caution = c.macro_risk in ("high", "very_high")
    if caution:
        return _mk(c, "caution", [], None, ["manual", "copilot"])

    return _mk(c, "eligible", [], None, ["manual", "copilot", "autopilot"])


def _mk(c: SetupCandidate, status, blocked, unblock, modes) -> SetupResult:
    return SetupResult(
        symbol=c.symbol, bias=c.bias, confirmation_score=c.confirmation_score,
        structure_state=c.structure_state, timeframe_alignment=c.timeframe_alignment,
        macro_risk=c.macro_risk, portfolio_overlap_pct=c.portfolio_overlap_pct,
        strategy_fit=c.strategy_fit, status=status, blocked_reasons=blocked,
        unblock_condition=unblock, modes_allowed=modes,
    )


def rank_setups(candidates: list[SetupCandidate]) -> list[SetupResult]:
    """Evaluate eligibility and rank by confirmation score (highest first).
    Blocked candidates are kept in the list, not hidden."""
    results = [_eligibility(c) for c in candidates]
    results.sort(key=lambda r: r.confirmation_score, reverse=True)
    return results


def strategy_fit_for(bias: str, structure_state: str) -> list[str]:
    """Suggest compatible strategies from bias + structure (research context)."""
    if bias == "bullish":
        fits = ["Momentum Swing", "Bull Put Spread"]
        if "uptrend" in structure_state:
            fits.append("Pullback Continuation")
        return fits
    if bias == "bearish":
        return ["Bear Call Spread", "Trend Short"]
    return ["Wait for confirmation"]
