"""
News-to-Risk Classification — Module 7.

Classifies an ALREADY-SOURCED news item or filing with DETERMINISTIC rules over
its title/form-type. It never invents headlines, sources, impact, or causal
explanations — it only labels evidence that already exists, and always reports
the reasoning + limitations + confidence.

Output fields: category, impact, direction, time_sensitivity, strategy_impact,
risk_action (advisory only — Phase 3 is informational, it changes no gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Category = Literal[
    "Earnings", "Regulatory", "Analyst", "Macro", "Insider",
    "Corporate Action", "Sector", "Market", "Other",
]
Impact = Literal["low", "moderate", "high"]
Direction = Literal["bullish", "bearish", "mixed", "uncertain"]
TimeSensitivity = Literal["immediate", "same_day", "multi_day", "long_term", "unknown"]
RiskAction = Literal["informational", "copilot_review", "reduce_size", "block_new_entries"]

# Keyword lexicons — transparent and auditable.
_BULLISH = ["beat", "beats", "surge", "soar", "record", "raises", "raised", "upgrade",
            "outperform", "buyback", "approval", "wins", "jumps", "rally", "strong"]
_BEARISH = ["miss", "misses", "plunge", "slump", "downgrade", "cuts", "cut", "lawsuit",
            "probe", "investigation", "recall", "warning", "falls", "drops", "weak", "halts"]
_ANALYST = ["upgrade", "downgrade", "price target", "initiates", "reiterates", "outperform", "underperform"]
_REGULATORY = ["sec", "fda", "doj", "ftc", "antitrust", "probe", "investigation", "lawsuit", "settlement", "recall"]
_MACRO = ["cpi", "inflation", "fed", "fomc", "rate", "jobs", "gdp", "treasury", "tariff"]
_CORP_ACTION = ["dividend", "buyback", "split", "spinoff", "merger", "acquisition", "acquire", "offering"]
_EARNINGS = ["earnings", "revenue", "guidance", "eps", "quarter", "results"]


@dataclass
class Classification:
    category: Category
    impact: Impact
    direction: Direction
    time_sensitivity: TimeSensitivity
    strategy_impact: str
    risk_action: RiskAction
    confidence: float
    explanation: str
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category, "impact": self.impact, "direction": self.direction,
            "time_sensitivity": self.time_sensitivity, "strategy_impact": self.strategy_impact,
            "risk_action": self.risk_action, "confidence": round(self.confidence, 2),
            "explanation": self.explanation, "limitations": self.limitations,
            "advisory_only": True,   # never changes a gate in Phase 3
        }


def _has(text: str, words: list[str]) -> list[str]:
    t = text.lower()
    return [w for w in words if w in t]


def classify(*, title: str = "", form_type: Optional[str] = None, is_filing: bool = False) -> Classification:
    text = title or ""
    limitations: list[str] = []

    # ── Category ──────────────────────────────────────────────────────────────
    if is_filing and form_type:
        if form_type in ("3", "4", "5", "3/A", "4/A", "5/A"):
            category: Category = "Insider"
        elif form_type.startswith("8-K"):
            category = "Corporate Action"
        elif form_type.startswith("10-"):
            category = "Earnings"
        else:
            category = "Regulatory"
    elif _has(text, _MACRO):
        category = "Macro"
    elif _has(text, _REGULATORY):
        category = "Regulatory"
    elif _has(text, _ANALYST):
        category = "Analyst"
    elif _has(text, _CORP_ACTION):
        category = "Corporate Action"
    elif _has(text, _EARNINGS):
        category = "Earnings"
    else:
        category = "Other"
        limitations.append("Category inferred from limited text — may be imprecise")

    # ── Direction (keyword-based; hedged) ─────────────────────────────────────
    bull = _has(text, _BULLISH)
    bear = _has(text, _BEARISH)
    if bull and bear:
        direction: Direction = "mixed"
    elif bull:
        direction = "bullish"
    elif bear:
        direction = "bearish"
    else:
        direction = "uncertain"
        limitations.append("No directional keywords found — direction is uncertain")

    # ── Impact ────────────────────────────────────────────────────────────────
    if category in ("Earnings", "Regulatory") or (category == "Corporate Action" and _has(text, ["merger", "acquisition", "acquire"])):
        impact: Impact = "high"
    elif category in ("Analyst", "Insider", "Macro", "Corporate Action"):
        impact = "moderate"
    else:
        impact = "low"

    # ── Time sensitivity ──────────────────────────────────────────────────────
    if category in ("Earnings", "Regulatory", "Insider"):
        time_sensitivity: TimeSensitivity = "same_day"
    elif category == "Analyst":
        time_sensitivity = "multi_day"
    elif category == "Macro":
        time_sensitivity = "multi_day"
    else:
        time_sensitivity = "unknown"

    # ── Strategy impact (research context) ───────────────────────────────────
    strategy_impact = {
        "Earnings": "Options spreads (avoid short premium into the print)",
        "Analyst": "Momentum / swing",
        "Macro": "ETF rotation / index options",
        "Insider": "Research context only — not a strategy trigger",
        "Corporate Action": "Event-driven",
        "Regulatory": "Elevated tail risk — reduce exposure",
    }.get(category, "No direct strategy impact")

    # ── Risk action (advisory) ────────────────────────────────────────────────
    if impact == "high" and direction == "bearish":
        risk_action: RiskAction = "block_new_entries"
    elif impact == "high":
        risk_action = "copilot_review"
    elif impact == "moderate" and direction in ("bearish", "mixed"):
        risk_action = "reduce_size"
    else:
        risk_action = "informational"

    # ── Confidence ────────────────────────────────────────────────────────────
    signals = len(bull) + len(bear) + (1 if category != "Other" else 0) + (1 if is_filing else 0)
    confidence = max(0.2, min(0.95, 0.35 + 0.15 * signals))

    explanation = (
        f"Classified as {category}/{direction} from "
        + (f"filing form {form_type}" if is_filing else "headline keywords")
        + (f"; bullish terms {bull}" if bull else "")
        + (f"; bearish terms {bear}" if bear else "")
    )
    limitations.append("Rule-based classification of sourced text — not a causal claim")

    return Classification(
        category=category, impact=impact, direction=direction,
        time_sensitivity=time_sensitivity, strategy_impact=strategy_impact,
        risk_action=risk_action, confidence=confidence,
        explanation=explanation, limitations=limitations,
    )
