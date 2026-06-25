"""Tests for RiskManager — position sizing, Kelly, and trade approval gates."""

from __future__ import annotations

from app.services.risk_manager import RiskManager, ProposedTrade, PortfolioRiskState


def _portfolio(**kw) -> PortfolioRiskState:
    base = dict(net_delta=0.0, net_vega=0.0, net_theta=0.0, open_position_count=0,
                portfolio_value=100000.0, positions_by_underlying={}, positions_by_sector={})
    base.update(kw)
    return PortfolioRiskState(**base)


def _trade(**kw) -> ProposedTrade:
    base = dict(strategy="bull_put_spread", underlying="SPY", sector="Index",
                delta=0.04, vega=0.02, max_loss_dollars=500.0)
    base.update(kw)
    return ProposedTrade(**base)


# ── position sizing ──────────────────────────────────────────────────────────
def test_calculate_position_size_basic():
    rm = RiskManager()
    # 100k × 2% = $2000 budget; $500 max loss → 4 contracts
    assert rm.calculate_position_size(100000, 500, risk_pct=0.02) == 4


def test_calculate_position_size_zero_when_budget_too_small():
    rm = RiskManager()
    assert rm.calculate_position_size(100, 500, risk_pct=0.02) == 0


def test_size_multiplier_halves():
    rm = RiskManager()
    full = rm.calculate_position_size(100000, 500, risk_pct=0.02, size_multiplier=1.0)
    half = rm.calculate_position_size(100000, 500, risk_pct=0.02, size_multiplier=0.5)
    assert half == full // 2


# ── Kelly ────────────────────────────────────────────────────────────────────
def test_kelly_valid_edge():
    rm = RiskManager()
    # wr .6, win .5, loss .5, 0.25 frac → 5% of 100k = 5000
    assert abs(rm.kelly_position_size(100000, 0.6, 0.5, 0.5, 0.25) - 5000) < 1.0


def test_kelly_invalid_inputs_fall_back_to_2pct():
    rm = RiskManager()
    assert rm.kelly_position_size(100000, 1.5, 0.5, 0.5) == 2000   # win_rate >= 1
    assert rm.kelly_position_size(100000, 0.6, 0.0, 0.5) == 2000   # avg_win <= 0


def test_kelly_negative_edge_falls_back():
    rm = RiskManager()
    assert rm.kelly_position_size(100000, 0.3, 0.5, 0.5) == 2000


def test_kelly_clamps_high_and_low():
    rm = RiskManager()
    high = rm.kelly_position_size(100000, 0.9, 0.5, 0.1, 0.25)
    assert abs(high - 8000) < 1.0          # capped at 8%
    low = rm.kelly_position_size(100000, 0.51, 1.0, 1.0, 0.01)
    assert abs(low - 1000) < 1.0           # floored at 1%


# ── approve_trade gates ──────────────────────────────────────────────────────
def test_blocks_on_max_positions():
    rm = RiskManager()
    a = rm.approve_trade(_trade(), _portfolio(open_position_count=rm.max_concurrent))
    assert not a.approved and "max_positions" in a.flags


def test_blocks_on_delta_limit():
    rm = RiskManager()
    a = rm.approve_trade(_trade(delta=0.05), _portfolio(net_delta=0.29))
    assert not a.approved and "delta_limit" in a.flags


def test_blocks_on_vega_limit():
    rm = RiskManager()
    a = rm.approve_trade(_trade(vega=0.05), _portfolio(net_vega=0.14))
    assert not a.approved and "vega_limit" in a.flags


def test_blocks_on_underlying_concentration():
    rm = RiskManager()
    a = rm.approve_trade(
        _trade(max_loss_dollars=2000, underlying="SPY"),
        _portfolio(positions_by_underlying={"SPY": 24000}),
    )
    assert not a.approved and "concentration_limit" in a.flags


def test_sector_concentration_is_warning_not_block():
    rm = RiskManager()
    a = rm.approve_trade(
        _trade(max_loss_dollars=2000, sector="Index", underlying="QQQ"),
        _portfolio(positions_by_sector={"Index": 39000}),
    )
    assert a.approved and "sector_concentration_warning" in a.flags


def test_clean_trade_approved_with_sizing():
    rm = RiskManager()
    a = rm.approve_trade(_trade(), _portfolio())
    assert a.approved and a.suggested_contracts > 0
    assert a.max_risk_dollars > 0 and a.reason is None
