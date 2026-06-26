"""
Dynamic Capital Allocation Engine.

Treats strategies as portfolio assets and decides what fraction of capital each
should receive, so money migrates toward strong strategies and away from weak
ones — automatically, every rebalance.

Pipeline per allocation:
  1. eligibility   — drop strategies the meta layer switched off (tilt == 0).
  2. raw weights   — by the chosen method (equal / risk_parity / vol_target /
                     performance / kelly / blended).
  3. meta tilt     — multiply each raw weight by its meta-strategy tilt.
  4. normalize     — to sum 1 across eligible strategies.
  5. cap + refill  — enforce max-per-strategy with proportional redistribution.
  6. deploy scale  — scale total to max_total_deployment; the remainder is cash.

Pure functions over dataclasses — no I/O — so the math is unit-tested to ≥95%.
The portfolio engine + API turn these weights into dollar envelopes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EQUAL = "equal"
RISK_PARITY = "risk_parity"
VOL_TARGET = "vol_target"
PERFORMANCE = "performance"
KELLY = "kelly"
BLENDED = "blended"

METHODS = (EQUAL, RISK_PARITY, VOL_TARGET, PERFORMANCE, KELLY, BLENDED)


@dataclass
class StrategyAlloc:
    strategy:        str
    score:           float = 50.0   # 0–100 health score (performance/blended)
    volatility:      float = 0.0    # annualized vol fraction (risk_parity/vol_target)
    expectancy:      float = 0.0    # $ per trade (performance weighting)
    kelly_fraction:  float = 0.0    # 0..1 (kelly weighting)
    tilt:            float = 1.0    # meta-strategy multiplier (0 ⇒ excluded)


@dataclass(frozen=True)
class AllocationConstraints:
    max_per_strategy:     float = 0.35   # hard cap on any single strategy
    max_total_deployment: float = 1.00   # cap on total capital deployed (rest = cash)
    target_volatility:    float = 0.15   # annualized target (vol_target method)


DEFAULT_CONSTRAINTS = AllocationConstraints()


@dataclass
class AllocationResult:
    method:       str
    weights:      dict[str, float]
    cash_weight:  float
    diagnostics:  dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "cash_weight": round(self.cash_weight, 4),
            "diagnostics": self.diagnostics,
        }


# ── raw weighting methods (return {strategy: raw_weight} over eligible) ────────────
def _equal(items: list[StrategyAlloc]) -> dict[str, float]:
    return {a.strategy: 1.0 for a in items}


def _inverse_vol(items: list[StrategyAlloc]) -> dict[str, float]:
    raw = {a.strategy: (1.0 / a.volatility if a.volatility > 1e-9 else 0.0) for a in items}
    return raw if sum(raw.values()) > 0 else _equal(items)


def _performance(items: list[StrategyAlloc]) -> dict[str, float]:
    # Weight by health score gated on positive expectancy (don't fund losers).
    raw = {a.strategy: (a.score if a.expectancy > 0 else 0.0) for a in items}
    return raw if sum(raw.values()) > 0 else _equal(items)


def _kelly(items: list[StrategyAlloc]) -> dict[str, float]:
    raw = {a.strategy: max(0.0, a.kelly_fraction) for a in items}
    return raw if sum(raw.values()) > 0 else _equal(items)


def _blended(items: list[StrategyAlloc]) -> dict[str, float]:
    # Average of three normalized views: inverse-vol, performance, score.
    views = [_normalize(_inverse_vol(items)),
             _normalize(_performance(items)),
             _normalize({a.strategy: max(0.0, a.score) for a in items} or _equal(items))]
    out: dict[str, float] = {}
    for v in views:
        for k, w in v.items():
            out[k] = out.get(k, 0.0) + w / len(views)
    return out


_METHOD_FNS = {
    EQUAL: _equal, RISK_PARITY: _inverse_vol, VOL_TARGET: _inverse_vol,
    PERFORMANCE: _performance, KELLY: _kelly, BLENDED: _blended,
}


# ── helpers ────────────────────────────────────────────────────────────────────────
def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: v / total for k, v in weights.items()}


def _apply_caps(weights: dict[str, float], cap: float) -> dict[str, float]:
    """Enforce a per-name cap, redistributing excess to uncapped names (water-fill)."""
    w = dict(weights)
    if cap >= 1.0 or not w:
        return w
    for _ in range(len(w) + 1):
        over = {k: v for k, v in w.items() if v > cap + 1e-12}
        if not over:
            break
        excess = sum(v - cap for v in over.values())
        for k in over:
            w[k] = cap
        uncapped = {k: v for k, v in w.items() if v < cap - 1e-12}
        room = sum(uncapped.values())
        if room <= 0:        # everything at cap → can't redistribute
            break
        for k in uncapped:
            w[k] += excess * (w[k] / room)
    return w


def _portfolio_vol(weights: dict[str, float], items: list[StrategyAlloc]) -> float:
    """Zero-correlation portfolio vol estimate: sqrt(sum (w_i * vol_i)^2)."""
    vol = {a.strategy: a.volatility for a in items}
    return sum((weights.get(k, 0.0) * vol.get(k, 0.0)) ** 2 for k in weights) ** 0.5


# ── main entry ───────────────────────────────────────────────────────────────────────
def allocate(strategies: list[StrategyAlloc], method: str = BLENDED,
             constraints: AllocationConstraints = DEFAULT_CONSTRAINTS) -> AllocationResult:
    """Compute target capital weights per strategy for the chosen method."""
    if method not in METHODS:
        raise ValueError(f"unknown allocation method '{method}'")

    eligible = [a for a in strategies if a.tilt > 0]
    if not eligible:
        return AllocationResult(method, {}, 1.0,
                                {"eligible": 0, "reason": "no eligible strategies"})

    raw = _METHOD_FNS[method](eligible)
    # Apply meta tilt, then normalize across eligible strategies.
    tilt = {a.strategy: a.tilt for a in eligible}
    tilted = {k: max(0.0, v) * tilt.get(k, 0.0) for k, v in raw.items()}
    weights = _normalize(tilted)
    if sum(weights.values()) <= 0:   # pragma: no cover - defensive; methods fall back to equal
        weights = _normalize({a.strategy: a.tilt for a in eligible})

    # Per-name cap with redistribution.
    weights = _apply_caps(weights, constraints.max_per_strategy)

    # Total-deployment scaling.
    deploy = max(0.0, min(1.0, constraints.max_total_deployment))
    if method == VOL_TARGET:
        # Additionally scale down if the (normalized) book's vol exceeds target.
        pvol = _portfolio_vol(weights, eligible)
        if pvol > 1e-9:
            deploy = min(deploy, constraints.target_volatility / pvol)
            deploy = max(0.0, min(1.0, deploy))
    weights = {k: v * deploy for k, v in weights.items()}

    deployed = sum(weights.values())
    return AllocationResult(
        method, weights, round(1.0 - deployed, 6),
        {"eligible": len(eligible), "deployment": round(deployed, 4),
         "method": method},
    )


def drift(current: dict[str, float], target: dict[str, float]) -> dict[str, float]:
    """Per-strategy weight drift (target − current) across the union of names."""
    keys = set(current) | set(target)
    return {k: round(target.get(k, 0.0) - current.get(k, 0.0), 4) for k in keys}
