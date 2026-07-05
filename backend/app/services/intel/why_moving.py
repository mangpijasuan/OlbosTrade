"""
"Why Is It Moving?" — deterministic driver assembler.

Given observable inputs the platform already computes (relative volume, gap,
VWAP relationship, sector/broad-market move, event proximity, options activity),
produce a structured explanation that STRICTLY separates:

  * facts        — directly observed, sourced numbers
  * inferences   — plausible drivers implied by the facts (never asserted as cause)
  * unknown      — data we don't have that would be needed for certainty

This never claims certainty about why a stock moved, and never invents a
headline or cause. If inputs are missing, they surface under `unknown`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MoveInputs:
    symbol: str
    change_pct: float | None = None          # today's % change
    relative_volume: float | None = None     # vs average
    gap_pct: float | None = None             # overnight gap
    vwap_relation: Optional[str] = None      # "above" | "below" | "reclaimed" | "lost"
    sector_change_pct: float | None = None
    market_change_pct: float | None = None   # SPY/QQQ proxy
    atr_extension: float | None = None       # move in ATRs (extension risk)
    days_to_earnings: int | None = None
    options_activity: Optional[str] = None   # "elevated" | "normal" | None
    news_detected: bool = False              # a sourced item exists (not the content)


@dataclass
class WhyMovingResult:
    symbol: str
    headline: str                            # neutral factual summary, not a claim
    facts: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "headline": self.headline,
            "facts": self.facts,
            "inferences": self.inferences,
            "risk_notes": self.risk_notes,
            "unknown": self.unknown,
        }


def explain_move(inp: MoveInputs) -> WhyMovingResult:
    facts: list[str] = []
    inferences: list[str] = []
    risk: list[str] = []
    unknown: list[str] = []

    # Neutral headline — states the observed move, makes no causal claim.
    if inp.change_pct is not None:
        headline = f"{inp.symbol} {inp.change_pct:+.1f}% today"
    else:
        headline = f"{inp.symbol} — move detected"

    # ── Facts (observed) ──────────────────────────────────────────────────────
    if inp.relative_volume is not None:
        facts.append(f"Relative volume is {inp.relative_volume:.1f}x normal")
    else:
        unknown.append("Relative volume unavailable")

    if inp.gap_pct is not None and abs(inp.gap_pct) >= 0.5:
        facts.append(f"Opened with a {inp.gap_pct:+.1f}% gap")

    if inp.vwap_relation:
        facts.append(f"Price {inp.vwap_relation} VWAP")

    if inp.sector_change_pct is not None:
        facts.append(f"Sector is {inp.sector_change_pct:+.1f}% today")
    if inp.market_change_pct is not None:
        facts.append(f"Broad market is {inp.market_change_pct:+.1f}% today")

    if inp.options_activity == "elevated":
        facts.append("Options activity is elevated")

    if inp.news_detected:
        facts.append("A sourced news item is available (see News & Filings)")
    else:
        unknown.append("No sourced news catalyst detected in available feeds")

    # ── Inferences (plausible, hedged — never asserted as the cause) ──────────
    if inp.relative_volume is not None and inp.relative_volume >= 2.0:
        inferences.append("Elevated volume suggests unusual participation")
    if inp.sector_change_pct is not None and inp.change_pct is not None:
        same_dir = (inp.sector_change_pct >= 0) == (inp.change_pct >= 0)
        if same_dir and abs(inp.sector_change_pct) >= 0.5:
            inferences.append("Move may be partly sector-driven rather than symbol-specific")
    if inp.vwap_relation in ("reclaimed", "lost"):
        inferences.append(f"VWAP {inp.vwap_relation} can indicate an intraday trend shift")

    # ── Risk notes ────────────────────────────────────────────────────────────
    if inp.atr_extension is not None and inp.atr_extension >= 1.5:
        risk.append(f"Price extended {inp.atr_extension:.1f} ATR beyond normal range")
    if inp.days_to_earnings is not None and 0 <= inp.days_to_earnings <= 10:
        risk.append(f"Earnings in {inp.days_to_earnings} days")

    # ── Unknowns (needed for certainty) ───────────────────────────────────────
    unknown.append("Intraday order flow and dark-pool prints are not available")

    return WhyMovingResult(
        symbol=inp.symbol,
        headline=headline,
        facts=facts,
        inferences=inferences,
        risk_notes=risk,
        unknown=unknown,
    )
