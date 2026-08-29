"""
Rotation Review — a pure, deterministic comparison of a held position
(the incumbent) against a blocked incoming signal (the challenger).

This module decides *nothing* and executes *nothing*. It produces a review
document. Closing the incumbent and opening the challenger requires explicit
human approval, enforced elsewhere (see position_rotation's approval guard).

Two rules govern everything here.

**Sunk cost is excluded from the decision.** A position's unrealized P&L is
carried on the review as context only, in a field named to make that
explicit, and never enters any comparison. Whether MRVL is down $11k has no
bearing on whether its remaining prospects beat the challenger's — the loss
is incurred either way. Closing it converts unrealized to realized, which is
an accounting event, not an edge. The engine that preceded this one ranked
candidates by "biggest loser", which is precisely the sunk-cost fallacy
mechanised.

**Nothing here is a calibrated probability, and nothing pretends to be.**
This system has no calibration layer. `signal_score` is a heuristic sum of
indicator points; Alpha Edge is a heuristic composite; the one trained model
scored r2 = -0.173 with 50.68% directional accuracy on n=442, which is a
coin flip. So there is no honest "Expected R" to compute, and this module
does not invent one. Every heuristic input is tagged UNCALIBRATED in the
output, and the composite is named for what it is. A review that reports
"Expected R = 1.7" would make a five-figure decision look rigorous while
resting on nothing; a review that reports "composite 62 vs 55 (UNCALIBRATED
— not a probability)" is honestly useful.

The single genuine probability estimate offered is
p_target_before_stop, from the driftless random-walk barrier result
(gambler's ruin): with absorbing barriers at distances `stop` and `target`
from the entry, P(target first) = stop / (stop + target). It assumes zero
drift and constant volatility, both stated on the output. It is a geometric
baseline, not a forecast, and it is deliberately the *only* number here that
carries probability semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

UNCALIBRATED = "UNCALIBRATED"

# A challenger must beat the incumbent's composite by at least this margin
# before replacement is even recommended. Two heuristics differing by a point
# or two is noise, and acting on noise churns capital and pays spread twice.
DEFAULT_MATERIALITY_MARGIN = 15.0

# Hard constraints. A challenger failing any of these is never recommended,
# regardless of how good its composite looks.
#
# Named FRACTION, not PCT, on purpose. portfolio_engine.compute_portfolio_risk
# returns portfolio_heat_pct as heat * 100 — a percent — and an earlier version
# of this module compared that directly against 0.35, so any book with more
# than 0.35% heat read as "over the limit" and vetoed every rotation. The unit
# is now in the name at both ends.
#
# The value assumes true risk-at-stake — sum of |entry - stop| x shares over
# capital — which is what _portfolio_heat_fraction() now supplies. It is NOT
# valid against portfolio_engine's notional-based portfolio_heat_pct, where a
# normally-invested book reads over 90%. Feeding that number here would make
# this constraint unsatisfiable, which is exactly what happened once.
#
# 0.35 sits above the desk's own per-trade sizing (risk_pct_per_trade = 0.02)
# times a Balanced cap of 3 concurrent positions = 6% expected, so it binds
# only when stops have widened well beyond plan or concurrency has grown.
MAX_PORTFOLIO_HEAT_FRACTION = 0.35

# Minimum current-volume / 20-day-average-volume for the challenger to count as
# tradable. Deliberately below equity_signal_engine's volume_ratio_threshold of
# 1.5 — that one is a signal-*quality* gate ("volume confirms the move"), a
# different question from "can this be entered without unusual slippage". A
# name trading at half its normal volume is quiet enough to be worth flagging;
# one at 0.9x is simply an ordinary day.
MIN_CHALLENGER_VOLUME_RATIO = 0.5


@dataclass(frozen=True)
class PositionFacts:
    """Facts about one side of the comparison. Every optional field may be
    None, which means "unknown" and is never silently read as zero."""

    ticker: str
    side: str                                  # "incumbent" | "challenger"
    direction: Optional[str] = None            # "long" | "short"

    # ── Heuristic scores. All UNCALIBRATED. ──────────────────────────────
    alpha_edge: Optional[float] = None         # 0-100 composite
    quality_score: Optional[float] = None      # hold score / entry score
    confidence: Optional[float] = None         # 0-1 heuristic, NOT a probability

    # ── Geometry, used for the one real probability estimate ─────────────
    stop_distance: Optional[float] = None      # price units, > 0
    target_distance: Optional[float] = None    # price units, > 0
    horizon_bars: Optional[int] = None

    # ── Hard constraints ─────────────────────────────────────────────────
    liquidity_ok: Optional[bool] = None
    in_flagged_cluster: Optional[bool] = None

    # ── Context only. NEVER used in any comparison. ──────────────────────
    # Named for what it is so that a future reader cannot mistake it for a
    # decision input. See the module docstring on sunk cost.
    unrealized_pnl_context_only: Optional[float] = None


def p_target_before_stop(
    stop_distance: Optional[float], target_distance: Optional[float]
) -> Optional[float]:
    """Driftless random-walk barrier estimate. None when geometry is unknown.

    P(target first) = stop / (stop + target). At the desk's standard 2x ATR
    stop and 4x ATR target this yields 1/3 — and the empirical record
    corroborates the direction of that: only 7.0% of resolved signal outcomes
    ever reached target, against a 20-bar horizon that censors most of the
    rest. Treat this as a geometric ceiling, not a forecast.
    """
    if stop_distance is None or target_distance is None:
        return None
    if stop_distance <= 0 or target_distance <= 0:
        return None
    return stop_distance / (stop_distance + target_distance)


def _composite(f: PositionFacts) -> Optional[float]:
    """Mean of whichever heuristic scores are present, on a 0-100 scale.

    Deliberately a plain average rather than a tuned weighting: weights
    fitted on 44 closed trades would be overfitting dressed as rigour, and
    this number is a discussion aid, not an expectancy. Returns None when no
    component is available — never a default that would let an unknown
    position compare as if it were average.
    """
    parts: list[float] = []
    if f.alpha_edge is not None:
        parts.append(float(f.alpha_edge))
    if f.quality_score is not None:
        parts.append(float(f.quality_score))
    if f.confidence is not None:
        parts.append(float(f.confidence) * 100.0)
    if not parts:
        return None
    return sum(parts) / len(parts)


def _hard_constraint_failures(
    challenger: PositionFacts, portfolio_heat_fraction: Optional[float]
) -> list[str]:
    """Constraints that veto a replacement outright. Unknown is not a pass:
    an unverifiable constraint blocks, because the cost of a wrong 'proceed'
    here is a real position closed and a real order sent."""
    fails: list[str] = []
    if challenger.liquidity_ok is None:
        fails.append("challenger_liquidity_unknown")
    elif challenger.liquidity_ok is False:
        fails.append("challenger_illiquid")
    if challenger.in_flagged_cluster is True:
        fails.append("challenger_in_flagged_correlation_cluster")
    if portfolio_heat_fraction is None:
        fails.append("portfolio_heat_unknown")
    elif portfolio_heat_fraction > MAX_PORTFOLIO_HEAT_FRACTION:
        fails.append(
            f"portfolio_heat_{portfolio_heat_fraction:.3f}"
            f"_over_{MAX_PORTFOLIO_HEAT_FRACTION}"
        )
    return fails


def _facts_dict(f: PositionFacts) -> dict:
    return {
        "ticker": f.ticker,
        "direction": f.direction,
        "alpha_edge": f.alpha_edge,
        "quality_score": f.quality_score,
        "confidence": f.confidence,
        "composite": _composite(f),
        "p_target_before_stop": p_target_before_stop(
            f.stop_distance, f.target_distance
        ),
        "stop_distance": f.stop_distance,
        "target_distance": f.target_distance,
        "horizon_bars": f.horizon_bars,
        "liquidity_ok": f.liquidity_ok,
        "in_flagged_cluster": f.in_flagged_cluster,
        # Prefixed and suffixed so it cannot be mistaken for a decision input
        # by a future reader skimming the payload.
        "unrealized_pnl_context_only": f.unrealized_pnl_context_only,
    }


def build_rotation_review(
    *,
    incumbent: PositionFacts,
    challenger: PositionFacts,
    portfolio_heat_fraction: Optional[float] = None,
    materiality_margin: float = DEFAULT_MATERIALITY_MARGIN,
) -> dict:
    """Compare one incumbent against one challenger. Pure and deterministic.

    Returns a review document with a `recommendation` of "replace", "hold" or
    "insufficient_data". A "replace" recommendation is a recommendation, not
    an instruction: nothing in this module or downstream of it may act on it
    without explicit human approval.
    """
    inc = _facts_dict(incumbent)
    chal = _facts_dict(challenger)

    reasons: list[str] = []
    inc_c, chal_c = inc["composite"], chal["composite"]

    if inc_c is None or chal_c is None:
        recommendation = "insufficient_data"
        missing = [
            s for s, c in (("incumbent", inc_c), ("challenger", chal_c)) if c is None
        ]
        reasons.append(
            "no heuristic score available for: " + ", ".join(missing)
            + " — cannot compare, so no replacement is recommended"
        )
        margin = None
        fails: list[str] = []
    else:
        margin = chal_c - inc_c
        fails = _hard_constraint_failures(challenger, portfolio_heat_fraction)
        if fails:
            recommendation = "hold"
            reasons.append("hard constraint(s) failed: " + ", ".join(fails))
        elif margin < materiality_margin:
            recommendation = "hold"
            reasons.append(
                f"challenger composite {chal_c:.1f} vs incumbent {inc_c:.1f} "
                f"= {margin:+.1f}, below the {materiality_margin:.1f} materiality "
                "margin — not a materially superior opportunity"
            )
        else:
            recommendation = "replace"
            reasons.append(
                f"challenger composite {chal_c:.1f} vs incumbent {inc_c:.1f} "
                f"= {margin:+.1f}, clearing the {materiality_margin:.1f} "
                "materiality margin"
            )

    return {
        "kind": "ROTATION_REVIEW",
        "recommendation": recommendation,
        "reasons": reasons,
        "incumbent": inc,
        "challenger": chal,
        "composite_margin": margin,
        "materiality_margin": materiality_margin,
        "portfolio_heat_fraction": portfolio_heat_fraction,
        "hard_constraint_failures": fails,
        # ── Truth-in-labelling. Read this before trusting any number above. ──
        "data_quality": {
            "alpha_edge": UNCALIBRATED,
            "quality_score": UNCALIBRATED,
            "confidence": UNCALIBRATED,
            "composite": UNCALIBRATED,
            "expected_r": "NOT_COMPUTED — no calibrated probability model exists",
            "p_target_before_stop": (
                "driftless random-walk barrier estimate; assumes zero drift and "
                "constant volatility; geometric baseline, not a forecast"
            ),
            "note": (
                "confidence is a heuristic indicator sum, not a probability. "
                "The only trained model scored r2=-0.173 / 50.68% directional "
                "accuracy (n=442) and is not in use."
            ),
        },
        "sunk_cost_excluded": True,
        "sunk_cost_note": (
            "unrealized_pnl_context_only is reported for context and is excluded "
            "from every comparison above. A position's existing loss is incurred "
            "whether or not it is closed, so it carries no information about "
            "which position has the better remaining prospects."
        ),
        # Load-bearing: consumers must not treat this document as executable.
        "requires_approval": True,
        "auto_executable": False,
    }
