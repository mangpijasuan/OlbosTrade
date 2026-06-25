"""
Options Intelligence engine.

Institutional-grade analytics for defined-risk vertical spreads, built on the
existing Black-Scholes pricer. Produces the probabilities and expected-value math
the Trade Frequency Controller and dashboard need:

    Probability of Profit (POP)      Probability ITM / OTM (short leg)
    Probability of Touch             Expected Move (1σ)
    Short-leg Greeks                 Expected Value ($ and per-$-risk)
    Kelly fraction

All risk-neutral / lognormal approximations — standard desk math, not look-ahead.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from scipy.stats import norm

from app.services.options_pricer import BlackScholesPricer

_pricer = BlackScholesPricer()


@dataclass
class SpreadIntelligence:
    pop: float                    # probability of profit (0..1)
    prob_itm_short: float         # P(short strike finishes ITM)
    prob_otm_short: float
    prob_touch_short: float       # P(price touches short strike before expiry)
    expected_move: float          # 1σ dollar move of the underlying over T
    breakeven: float
    delta_short: float
    theta_short: float
    vega_short: float
    iv_used: float
    max_profit: float             # per contract ($)
    max_loss: float               # per contract ($)
    reward_risk: float            # max_profit / max_loss
    expected_value: float         # per contract ($) = POP·maxP − (1−POP)·maxL
    ev_per_risk: float            # EV / max_loss (unitless)
    kelly_fraction: float         # full-Kelly stake fraction (clamp ≥ 0)

    def as_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return d1 - sigma * math.sqrt(T)


def analyze_spread(
    *,
    spot: float,
    short_strike: float,
    long_strike: float,
    option_type: str,           # "put" (bull put) | "call" (bear call)
    dte: float,                 # days to expiry
    iv: float,                  # implied vol (decimal, e.g. 0.20)
    credit_per_share: float,    # net credit received per share
    r: float = 0.05,
) -> SpreadIntelligence:
    """Analyze a vertical CREDIT spread. Raises ValueError on degenerate input."""
    if spot <= 0 or short_strike <= 0 or long_strike <= 0:
        raise ValueError("spot and strikes must be positive")
    if dte <= 0:
        raise ValueError("dte must be positive")
    if iv <= 0:
        raise ValueError("iv must be positive")

    is_call = option_type == "call"
    T = dte / 365.0
    width = abs(short_strike - long_strike)
    if width <= 0:
        raise ValueError("spread width must be positive")
    credit = max(0.0, float(credit_per_share))
    max_profit = round(credit * 100, 2)
    max_loss = round(max(width - credit, 0.0) * 100, 2)
    reward_risk = round(credit / (width - credit), 4) if width - credit > 1e-9 else 0.0

    # Breakeven of the credit spread.
    breakeven = short_strike + credit if is_call else short_strike - credit

    # Risk-neutral probabilities (N(d2) = P(S_T > K)).
    d2_short = _d2(spot, short_strike, T, r, iv)
    d2_be = _d2(spot, breakeven, T, r, iv)
    if is_call:
        prob_itm_short = float(norm.cdf(d2_short))        # P(S_T > short call strike)
        pop = float(norm.cdf(-d2_be))                     # profit if S_T < breakeven
    else:
        prob_itm_short = float(norm.cdf(-d2_short))        # P(S_T < short put strike)
        pop = float(norm.cdf(d2_be))                       # profit if S_T > breakeven
    prob_otm_short = 1.0 - prob_itm_short
    prob_touch_short = min(1.0, 2.0 * prob_itm_short)      # standard touch approximation

    expected_move = spot * iv * math.sqrt(T)

    # Short-leg Greeks.
    delta_short = _pricer.delta(spot, short_strike, T, r, iv, option_type)
    theta_short = _pricer.theta(spot, short_strike, T, r, iv, option_type)
    vega_short = _pricer.vega(spot, short_strike, T, r, iv)

    # Expected value of the defined-risk spread.
    ev = pop * max_profit - (1.0 - pop) * max_loss
    ev_per_risk = ev / max_loss if max_loss > 0 else 0.0

    # Kelly: f* = (b·p − q) / b, b = reward:risk, p = POP, q = 1−POP.
    b = reward_risk
    kelly = (b * pop - (1.0 - pop)) / b if b > 1e-9 else 0.0
    kelly = max(0.0, min(1.0, kelly))

    return SpreadIntelligence(
        pop=pop,
        prob_itm_short=prob_itm_short,
        prob_otm_short=prob_otm_short,
        prob_touch_short=prob_touch_short,
        expected_move=round(expected_move, 4),
        breakeven=round(breakeven, 4),
        delta_short=round(delta_short, 4),
        theta_short=round(theta_short, 4),
        vega_short=round(vega_short, 4),
        iv_used=round(iv, 4),
        max_profit=max_profit,
        max_loss=max_loss,
        reward_risk=reward_risk,
        expected_value=round(ev, 2),
        ev_per_risk=round(ev_per_risk, 4),
        kelly_fraction=round(kelly, 4),
    )
