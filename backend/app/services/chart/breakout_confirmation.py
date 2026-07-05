"""
Breakout / pullback confirmation — Module 7.

A breakout is NOT confirmed until configured, closed-bar rules are met. This
engine returns an explainable status (none / detected / confirmed) with the
evidence satisfied and, when pending, the exact reason it is not yet confirmed.

Pure and deterministic — the route supplies the live inputs. Every strategy can
define its own confirmation requirements via ConfirmationRules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Status = Literal["none", "detected", "confirmed"]
Kind = Literal["breakout", "breakdown", "pullback_continuation"]


@dataclass
class ConfirmationRules:
    min_relative_volume: float = 1.3
    require_vwap_hold: bool = True
    require_mtf_agreement: bool = True
    require_event_clear: bool = True    # no high-impact event within the window


@dataclass
class BreakoutInputs:
    kind: Kind
    close: float
    level: float                        # resistance (breakout) or support (breakdown)
    closed_bar: bool                    # is the signal built on a completed candle
    relative_volume: Optional[float]
    above_vwap: Optional[bool]
    mtf_agrees: Optional[bool]          # multi-timeframe trend agrees with direction
    event_clear: Optional[bool]         # True = no high-impact event in window


@dataclass
class BreakoutResult:
    kind: Kind
    status: Status
    evidence: list[str] = field(default_factory=list)
    pending_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "status": self.status,
            "evidence": self.evidence,
            "pending_reasons": self.pending_reasons,
        }


def assess_breakout(inp: BreakoutInputs, rules: ConfirmationRules | None = None) -> BreakoutResult:
    rules = rules or ConfirmationRules()
    evidence: list[str] = []
    pending: list[str] = []

    crossed = (
        inp.close > inp.level if inp.kind in ("breakout", "pullback_continuation")
        else inp.close < inp.level
    )
    if not crossed:
        return BreakoutResult(inp.kind, "none",
                              pending_reasons=[f"price has not crossed the {inp.level:.2f} level"])

    # Crossed — now check the confirmation gates (all on a closed bar).
    if inp.close > inp.level and inp.kind != "breakdown":
        evidence.append(f"closed above {inp.level:.2f}")
    elif inp.kind == "breakdown":
        evidence.append(f"closed below {inp.level:.2f}")

    if not inp.closed_bar:
        pending.append("candle has not closed above the level")

    if inp.relative_volume is not None:
        if inp.relative_volume >= rules.min_relative_volume:
            evidence.append(f"relative volume {inp.relative_volume:.1f}x")
        else:
            pending.append(f"relative volume {inp.relative_volume:.1f}x below {rules.min_relative_volume:.1f}x")
    elif rules.min_relative_volume > 0:
        pending.append("relative volume unavailable")

    if rules.require_vwap_hold:
        if inp.above_vwap is True:
            evidence.append("held above VWAP")
        elif inp.above_vwap is False:
            pending.append("not holding above VWAP")
        else:
            pending.append("VWAP relationship unavailable")

    if rules.require_mtf_agreement:
        if inp.mtf_agrees is True:
            evidence.append("multi-timeframe trend aligned")
        elif inp.mtf_agrees is False:
            pending.append("multi-timeframe trend not aligned")
        else:
            pending.append("timeframe alignment unavailable")

    if rules.require_event_clear:
        if inp.event_clear is True:
            evidence.append("no high-impact event in window")
        elif inp.event_clear is False:
            pending.append("high-impact event within the window")

    status: Status = "confirmed" if not pending else "detected"
    return BreakoutResult(inp.kind, status, evidence=evidence, pending_reasons=pending)
