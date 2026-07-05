"""
Market Structure engine — explainable, deterministic.

Detects swing highs/lows from closed bars, classifies the recent sequence
(higher-high/higher-low, lower-high/lower-low, range), and derives simple
support/resistance zones. Uses clear, neutral naming.

IMPORTANT: this makes NO claim about institutional intent. Break-of-Structure
and Change-of-Character are described as chart events only. Optional overlays
(liquidity sweeps, fair value gaps, order blocks) are NOT implemented in
Phase 1 and, if added later, must be labelled "Technical pattern overlay —
validation required" and disabled by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

StructureState = Literal[
    "uptrend", "downtrend", "range", "uptrend_weakening", "downtrend_weakening", "undetermined"
]


@dataclass
class Swing:
    index: int
    price: float
    kind: Literal["high", "low"]


@dataclass
class StructureResult:
    state: StructureState
    recent_event: str                      # neutral description, e.g. "higher high formed"
    support: list[float] = field(default_factory=list)
    resistance: list[float] = field(default_factory=list)
    swings: list[Swing] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "recent_event": self.recent_event,
            "support": [round(s, 2) for s in self.support],
            "resistance": [round(r, 2) for r in self.resistance],
            "swing_count": len(self.swings),
            "note": self.note,
        }


def _find_swings(highs: list[float], lows: list[float], left: int = 3, right: int = 3) -> list[Swing]:
    """Fractal-style swing detection: a swing high is higher than `left` bars
    before and `right` bars after (mirror for swing lows)."""
    swings: list[Swing] = []
    n = len(highs)
    for i in range(left, n - right):
        window_h = highs[i - left:i + right + 1]
        window_l = lows[i - left:i + right + 1]
        if highs[i] == max(window_h) and window_h.count(highs[i]) == 1:
            swings.append(Swing(i, highs[i], "high"))
        elif lows[i] == min(window_l) and window_l.count(lows[i]) == 1:
            swings.append(Swing(i, lows[i], "low"))
    return swings


def analyze_structure(bars: list[dict]) -> StructureResult:
    """Analyze structure from CLOSED bars (oldest→newest)."""
    if len(bars) < 20:
        return StructureResult("undetermined", "insufficient bars", note="need >= 20 bars")

    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    swings = _find_swings(highs, lows)

    swing_highs = [s for s in swings if s.kind == "high"]
    swing_lows = [s for s in swings if s.kind == "low"]

    state: StructureState = "range"
    event = "range-bound"

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1].price > swing_highs[-2].price
        hl = swing_lows[-1].price > swing_lows[-2].price
        lh = swing_highs[-1].price < swing_highs[-2].price
        ll = swing_lows[-1].price < swing_lows[-2].price
        if hh and hl:
            state, event = "uptrend", "higher high and higher low"
        elif ll and lh:
            state, event = "downtrend", "lower high and lower low"
        elif hh and ll:
            state, event = "range", "expanding range (higher high, lower low)"
        elif lh and hl:
            state, event = "range", "contracting range"
        elif hl and not hh:
            state, event = "uptrend_weakening", "higher low but lower high — momentum fading"
        elif lh and not ll:
            state, event = "downtrend_weakening", "lower high but higher low — downside fading"

    # Support/resistance: cluster recent swing prices.
    resistance = sorted({round(s.price, 2) for s in swing_highs[-3:]}, reverse=True)
    support = sorted({round(s.price, 2) for s in swing_lows[-3:]}, reverse=True)

    return StructureResult(
        state=state,
        recent_event=event,
        support=support,
        resistance=resistance,
        swings=swings[-8:],
        note="chart structure only — no institutional-intent claim",
    )
