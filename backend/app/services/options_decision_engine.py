"""
Options Decision Engine — turn a directional signal into an EV-ranked options trade.

Given a direction + confidence and candidate vertical spreads (spot, IV, DTE,
strikes, net price), this evaluates ALL applicable verticals — Bull Put, Bear
Call (credit) and Bull Call, Bear Put (debit) — and for each computes:

  probability of profit · max gain · max loss · risk/reward · expected value ·
  capped Kelly fraction · breakeven

then ranks by EV, picks the best, assigns a 0–100 Trade Score, and applies a
fail-closed NO-TRADE gate (EV/POP/RR/confidence thresholds). This is what makes
an options signal actionable and EV-optimized — not "SPY is bullish" but
"Bull Put 745/740, POP 78%, EV +$32, R:R 1:2, score 82."

Pure & deterministic (Black-Scholes lognormal probabilities); no I/O — fully unit
tested. Live strike/price selection from the chain is a thin wrapper elsewhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

from scipy.stats import norm

# Which verticals are appropriate for each directional bias.
CREDIT = {"bull_put", "bear_call"}
DEBIT = {"bull_call", "bear_put"}
BULLISH_SPREADS = {"bull_put", "bull_call"}
BEARISH_SPREADS = {"bear_call", "bear_put"}


def _prob_above(spot: float, strike: float, dte: float, iv: float, r: float = 0.04) -> float:
    """Lognormal P(S_T > strike) via Black-Scholes d2."""
    T = max(dte, 0.0) / 365.0
    if spot <= 0 or strike <= 0 or iv <= 0 or T <= 0:
        return 0.0
    d2 = (math.log(spot / strike) + (r - 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
    return float(norm.cdf(d2))


def kelly_fraction(pop: float, max_gain: float, max_loss: float, *, cap: float = 0.25) -> float:
    """
    Fractional Kelly for a two-outcome bet. b = win/loss odds; f* = p - (1-p)/b.
    Floored at 0 (never bet a negative edge) and capped (default 25%).
    """
    if max_loss <= 0 or max_gain <= 0:
        return 0.0
    b = max_gain / max_loss
    f = pop - (1.0 - pop) / b
    return round(max(0.0, min(f, cap)), 4)


def evaluate_vertical(*, kind: str, spot: float, short_strike: float,
                      long_strike: float, net_price: float, dte: float,
                      iv: float) -> dict:
    """
    Evaluate one vertical spread. `net_price` is the per-share magnitude: the
    credit received (credit spreads) or debit paid (debit spreads), > 0.
    Returns POP, max gain/loss ($ per contract), R:R, EV, Kelly, breakeven.
    """
    if kind not in CREDIT | DEBIT:
        raise ValueError(f"unknown vertical kind: {kind}")
    width = abs(short_strike - long_strike)
    net = abs(net_price)
    mult = 100.0

    if kind in CREDIT:
        # Full profit if the short leg expires OTM; breakeven off the short strike.
        max_gain = net * mult
        max_loss = max((width - net), 0.0) * mult
        if kind == "bull_put":
            breakeven = short_strike - net
            pop = _prob_above(spot, breakeven, dte, iv)            # profit if S_T > BE
        else:  # bear_call
            breakeven = short_strike + net
            pop = 1.0 - _prob_above(spot, breakeven, dte, iv)      # profit if S_T < BE
    else:  # DEBIT — breakeven off the long (bought) leg
        max_gain = max((width - net), 0.0) * mult
        max_loss = net * mult
        if kind == "bull_call":
            breakeven = long_strike + net
            pop = _prob_above(spot, breakeven, dte, iv)            # profit if S_T > BE
        else:  # bear_put
            breakeven = long_strike - net
            pop = 1.0 - _prob_above(spot, breakeven, dte, iv)      # profit if S_T < BE

    pop = round(float(pop), 4)
    rr = round(max_gain / max_loss, 4) if max_loss > 0 else None
    # Two-outcome EV using POP (standard honest approximation).
    ev = round(pop * max_gain - (1.0 - pop) * max_loss, 2)
    return {
        "kind": kind,
        "type": "CREDIT" if kind in CREDIT else "DEBIT",
        "short_strike": short_strike,
        "long_strike": long_strike,
        "width": round(width, 2),
        "net_price": round(net, 4),
        "breakeven": round(breakeven, 2),
        "pop": pop,
        "max_gain": round(max_gain, 2),
        "max_loss": round(max_loss, 2),
        "risk_reward": rr,
        "expected_value": ev,
        "kelly_fraction": kelly_fraction(pop, max_gain, max_loss),
    }


def trade_score(*, pop: float, expected_value: float, risk_reward: Optional[float],
                confidence: float) -> int:
    """
    0–100 blend: POP (40) + risk/reward (25) + positive-EV (20) + confidence (15).
    """
    rr_component = min((risk_reward or 0.0) / 2.0, 1.0)   # R:R of 2 → full marks
    ev_component = 1.0 if expected_value > 0 else 0.0
    score = 100.0 * (0.40 * max(0.0, min(pop, 1.0))
                     + 0.25 * rr_component
                     + 0.20 * ev_component
                     + 0.15 * max(0.0, min(confidence, 1.0)))
    return int(round(max(0, min(100, score))))


@dataclass
class Decision:
    decision: str          # "TRADE" | "NO_TRADE"
    direction: str
    best: Optional[dict]
    trade_score: int
    ranked: list
    reasoning: list

    def to_dict(self) -> dict:
        return asdict(self)


def decide(
    candidates: list[dict],
    *,
    direction: str,
    confidence: float,
    min_ev: float = 0.0,
    min_pop: float = 0.55,
    min_rr: float = 0.25,
    min_confidence: float = 0.0,
) -> Decision:
    """
    Rank direction-appropriate candidates by EV and apply the NO-TRADE gate.

    ``candidates`` are dicts from :func:`evaluate_vertical`. Only spreads matching
    the directional bias are considered. Returns a Decision — TRADE with the best
    spread + score, or NO_TRADE with the reasons.
    """
    reasoning: list[str] = []
    allowed = (BULLISH_SPREADS if direction == "BULLISH"
               else BEARISH_SPREADS if direction == "BEARISH" else set())
    if not allowed:
        return Decision("NO_TRADE", direction, None, 0, [],
                        ["no directional bias — stay in cash"])

    pool = [c for c in candidates if c.get("kind") in allowed]
    # Rank by EV desc, then POP desc.
    pool.sort(key=lambda c: (c.get("expected_value", 0), c.get("pop", 0)), reverse=True)

    if confidence < min_confidence:
        return Decision("NO_TRADE", direction, None, 0, pool,
                        [f"confidence {confidence:.2f} < {min_confidence:.2f}"])
    if not pool:
        return Decision("NO_TRADE", direction, None, 0, [],
                        ["no candidate spreads for this direction"])

    best = pool[0]
    score = trade_score(pop=best["pop"], expected_value=best["expected_value"],
                        risk_reward=best["risk_reward"], confidence=confidence)

    if best["expected_value"] <= min_ev:
        reasoning.append(f"best EV {best['expected_value']} ≤ min {min_ev}")
    if best["pop"] < min_pop:
        reasoning.append(f"best POP {best['pop']} < min {min_pop}")
    if (best["risk_reward"] or 0) < min_rr:
        reasoning.append(f"best R:R {best['risk_reward']} < min {min_rr}")

    if reasoning:
        return Decision("NO_TRADE", direction, None, score, pool, reasoning)

    reasoning.append(
        f"{best['kind']} {best['short_strike']}/{best['long_strike']} — "
        f"POP {best['pop']:.0%}, EV {best['expected_value']}, R:R {best['risk_reward']}"
    )
    return Decision("TRADE", direction, best, score, pool, reasoning)
