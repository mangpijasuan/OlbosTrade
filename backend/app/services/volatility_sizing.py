"""
Volatility-based position sizing.

Inverse-volatility scaling: deploy more when the tape is calm, less when it is
fearful — so dollar risk stays roughly constant across regimes instead of
ballooning exactly when realised moves get violent. The scalar multiplies the
existing risk budget (regime multiplier × mode risk-per-trade %); it never sizes
a trade UP past a hard cap, and floors it so a single vol spike can't zero out
activity entirely.

Two inputs:
  • VIX        — absolute fear gauge. Size ∝ target_vix / vix.
  • IV rank    — relative richness. Trim at extremes: very high IV rank carries
                 tail risk; very low IV rank means thin premium / poor edge.

Pure functions over floats — trivially testable, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VolSizingConfig:
    target_vix: float = 18.0   # VIX at which the scalar is ~1.0
    floor:      float = 0.40   # never size below 40% of the base budget
    cap:        float = 1.25   # never size above 125% of the base budget
    high_ivr:   float = 70.0   # IV rank above this → tail-risk trim
    low_ivr:    float = 20.0   # IV rank below this → thin-premium trim
    high_ivr_factor: float = 0.80
    low_ivr_factor:  float = 0.90


DEFAULT_CONFIG = VolSizingConfig()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _ivr_factor(iv_rank: float, cfg: VolSizingConfig) -> float:
    if iv_rank >= cfg.high_ivr:
        return cfg.high_ivr_factor
    if iv_rank <= cfg.low_ivr:
        return cfg.low_ivr_factor
    return 1.0


def volatility_scalar(iv_rank: float, vix: float,
                      cfg: VolSizingConfig = DEFAULT_CONFIG) -> float:
    """
    0..cap multiplier on the base risk budget. 1.0 at target VIX with mid IV
    rank; shrinks as VIX rises; trimmed further at IV-rank extremes; clamped to
    [floor, cap]. A non-positive VIX is treated as missing → neutral 1.0.
    """
    if vix <= 0:
        return 1.0
    vix_factor = cfg.target_vix / vix
    raw = vix_factor * _ivr_factor(iv_rank, cfg)
    return round(_clamp(raw, cfg.floor, cfg.cap), 4)


def vol_adjusted_multiplier(base_multiplier: float, iv_rank: float, vix: float,
                            cfg: VolSizingConfig = DEFAULT_CONFIG) -> float:
    """Combine an existing size multiplier (e.g. regime) with the vol scalar."""
    return round(max(0.0, base_multiplier) * volatility_scalar(iv_rank, vix, cfg), 4)


def describe(iv_rank: float, vix: float,
             cfg: VolSizingConfig = DEFAULT_CONFIG) -> dict:
    """Explain the sizing decision (for logs, the API, and the UI)."""
    scalar = volatility_scalar(iv_rank, vix, cfg)
    if scalar >= 1.0:
        stance = "full"
    elif scalar <= cfg.floor + 1e-9:
        stance = "minimum"
    else:
        stance = "reduced"
    return {
        "vix": round(vix, 2),
        "iv_rank": round(iv_rank, 2),
        "scalar": scalar,
        "ivr_factor": _ivr_factor(iv_rank, cfg),
        "stance": stance,
        "target_vix": cfg.target_vix,
    }
