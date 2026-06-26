"""
Scenario / Stress Engine.

Deterministically reprices positions under named market shocks (crash, vol spike,
rate shock, gaps, flash crash) using the existing Black-Scholes pricer, so you can
see — before it happens — what a violent move does to a position or the whole
book. Pure functions over position dicts; no I/O, no randomness.

A position is a dict:
    {"symbol", "kind": "option"|"equity", "option_type": "call"|"put",
     "spot", "strike", "dte_days", "iv", "r", "quantity", "multiplier"}
quantity is signed (+ long, − short); multiplier is 100 for options, 1 for equity.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.options_pricer import BlackScholesPricer

_pricer = BlackScholesPricer()


@dataclass(frozen=True)
class Shock:
    name:         str
    spot_pct:     float = 0.0    # fractional move in underlying (e.g. -0.20)
    iv_mult:      float = 1.0    # multiply implied vol
    iv_add:       float = 0.0    # add to implied vol (absolute, e.g. +0.10)
    rate_add:     float = 0.0    # add to the risk-free rate
    dte_add_days: int = 0        # change days-to-expiry (e.g. time decay)

    def as_dict(self) -> dict:
        return {"name": self.name, "spot_pct": self.spot_pct, "iv_mult": self.iv_mult,
                "iv_add": self.iv_add, "rate_add": self.rate_add,
                "dte_add_days": self.dte_add_days}


# Standard stress set.
DEFAULT_SCENARIOS: list[Shock] = [
    Shock("market_crash", spot_pct=-0.20, iv_mult=1.8),
    Shock("vol_spike", spot_pct=0.0, iv_add=0.25),
    Shock("rate_shock", rate_add=0.01),
    Shock("gap_down", spot_pct=-0.08, iv_mult=1.3),
    Shock("gap_up", spot_pct=0.08, iv_mult=0.9),
    Shock("flash_crash", spot_pct=-0.12, iv_mult=2.5),
]


def position_value(pos: dict, *, spot: float | None = None, iv: float | None = None,
                   r: float | None = None, dte_days: float | None = None) -> float:
    """Mark a position to model. Overrides default to the position's own params."""
    qty = float(pos.get("quantity", 0))
    mult = float(pos.get("multiplier", 100 if pos.get("kind") == "option" else 1))
    s = spot if spot is not None else float(pos["spot"])
    if pos.get("kind") == "equity":
        return s * qty * mult
    k = float(pos["strike"])
    sigma = max(0.0001, iv if iv is not None else float(pos["iv"]))
    rate = r if r is not None else float(pos.get("r", 0.04))
    days = dte_days if dte_days is not None else float(pos.get("dte_days", 0))
    T = max(0.0, days / 365.0)
    if pos.get("option_type") == "put":
        px = _pricer.put_price(s, k, T, rate, sigma)
    else:
        px = _pricer.call_price(s, k, T, rate, sigma)
    return px * qty * mult


def apply_shock(pos: dict, shock: Shock) -> dict:
    """Baseline vs shocked value (and P&L) for a single position."""
    base = position_value(pos)
    spot = float(pos["spot"]) * (1.0 + shock.spot_pct)
    iv = max(0.0001, float(pos.get("iv", 0.0)) * shock.iv_mult + shock.iv_add)
    r = float(pos.get("r", 0.04)) + shock.rate_add
    days = float(pos.get("dte_days", 0)) + shock.dte_add_days
    shocked = position_value(pos, spot=spot, iv=iv, r=r, dte_days=days)
    return {"symbol": pos.get("symbol"), "baseline": round(base, 2),
            "shocked": round(shocked, 2), "pnl": round(shocked - base, 2)}


def run_scenario(positions: list[dict], shock: Shock,
                 capital: float = 0.0) -> dict:
    """Apply one shock across the book → per-position + portfolio P&L."""
    legs = [apply_shock(p, shock) for p in positions]
    total = round(sum(l["pnl"] for l in legs), 2)
    return {
        "scenario": shock.name,
        "shock": shock.as_dict(),
        "portfolio_pnl": total,
        "portfolio_pnl_pct": round(total / capital * 100, 2) if capital > 0 else None,
        "positions": legs,
    }


def run_all(positions: list[dict], capital: float = 0.0,
            scenarios: list[Shock] | None = None) -> dict:
    """Run the full stress set; worst scenario first."""
    shocks = scenarios if scenarios is not None else DEFAULT_SCENARIOS
    results = [run_scenario(positions, s, capital) for s in shocks]
    results.sort(key=lambda r: r["portfolio_pnl"])
    worst = results[0] if results else None
    return {
        "scenarios": results,
        "worst_scenario": worst["scenario"] if worst else None,
        "worst_pnl": worst["portfolio_pnl"] if worst else 0.0,
    }
