"""
Batch 3 (3-E) — concentration limits must score the TOTAL position.

approve_trade carries per-unit figures; the gate passes position_quantity (the
sized contract/share count) so single-underlying / sector concentration is
scored against the whole position. Previously a per-unit max_loss was compared
to the entire portfolio, so the limit effectively never bound.
"""

from __future__ import annotations

from app.services.risk_manager import (
    RiskManager, ProposedTrade, PortfolioRiskState,
)


def _state():
    # Large book so the 2% per-trade budget affords the contract (isolates the
    # concentration check from the unrelated below_min_size sizing check).
    return PortfolioRiskState(
        net_delta=0.0, net_vega=0.0, net_theta=0.0,
        open_position_count=0, portfolio_value=100_000.0,
        positions_by_underlying={}, positions_by_sector={},
    )


def _trade():
    return ProposedTrade(
        strategy="bull_put_spread", underlying="SPY", sector="tech",
        delta=0.0, vega=0.0, max_loss_dollars=1_000.0,
    )


def test_single_unit_within_concentration():
    # 1 contract = $1,000 = 1% < 25% limit → approved.
    appr = RiskManager().approve_trade(_trade(), _state(), position_quantity=1)
    assert appr.approved is True


def test_quantity_scaled_exposure_breaches_concentration():
    # 30 contracts = $30,000 = 30% > 25% single-underlying limit → blocked.
    appr = RiskManager().approve_trade(_trade(), _state(), position_quantity=30)
    assert appr.approved is False
    assert "concentration_limit" in appr.flags


def test_default_quantity_is_one():
    # Backward-compatible default: no position_quantity == 1 unit.
    appr = RiskManager().approve_trade(_trade(), _state())
    assert appr.approved is True
