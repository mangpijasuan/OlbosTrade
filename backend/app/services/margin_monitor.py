"""
Margin monitor — buying-power-reduction / margin-utilization tracking.

Nominal P&L loss limits don't catch a margin call: a volatility spike can blow
up the maintenance-margin requirement on multi-leg options even while position
P&L looks stable. This module turns the broker's account figures into a single
utilization metric + an ok/warn/critical status, used by the Risk dashboard and
as a pre-trade guardrail.

Pure functions only — no broker/IO — so it is trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class MarginStatus:
    net_liquidation:    float
    maintenance_margin: float
    excess_liquidity:   float
    buying_power:       float
    init_margin:        float
    utilization_pct:    float   # maintenance_margin / net_liquidation * 100
    status:             str     # "ok" | "warn" | "critical"
    detail:             str

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_margin(
    *,
    net_liquidation:    float,
    maintenance_margin: float,
    excess_liquidity:   float,
    buying_power:       float = 0.0,
    init_margin:        float = 0.0,
    warn_pct:           float = 0.50,
    critical_pct:       float = 0.80,
) -> MarginStatus:
    """
    Compute margin utilization and a severity status.

    utilization = maintenance_margin / net_liquidation. Status is ``critical``
    when utilization >= ``critical_pct`` OR excess liquidity has gone non-positive
    (a margin call is imminent/active), ``warn`` at >= ``warn_pct``, else ``ok``.
    """
    nl = float(net_liquidation or 0.0)
    mm = max(float(maintenance_margin or 0.0), 0.0)
    el = float(excess_liquidity or 0.0)

    utilization = (mm / nl * 100.0) if nl > 0 else (100.0 if mm > 0 else 0.0)
    utilization = round(utilization, 2)

    warn = warn_pct * 100.0
    crit = critical_pct * 100.0

    if el <= 0 and mm > 0:
        status = "critical"
        detail = "Excess liquidity exhausted — margin call risk"
    elif utilization >= crit:
        status = "critical"
        detail = f"Margin utilization {utilization:.1f}% ≥ {crit:.0f}% critical"
    elif utilization >= warn:
        status = "warn"
        detail = f"Margin utilization {utilization:.1f}% ≥ {warn:.0f}% warning"
    else:
        status = "ok"
        detail = f"Margin utilization {utilization:.1f}% nominal"

    return MarginStatus(
        net_liquidation=round(nl, 2),
        maintenance_margin=round(mm, 2),
        excess_liquidity=round(el, 2),
        buying_power=round(float(buying_power or 0.0), 2),
        init_margin=round(float(init_margin or 0.0), 2),
        utilization_pct=utilization,
        status=status,
        detail=detail,
    )
