"""Step 8 — execution portfolio gate (pure + OMS wiring)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.execution_portfolio_gate import (
    PortfolioGateResult,
    estimate_proposed_risk_dollars,
    evaluate_portfolio_gates,
)
from app.services.risk_manager import PortfolioRiskState, RiskManager


def _portfolio(
    *,
    value: float = 100_000.0,
    open_count: int = 0,
    by_u: dict | None = None,
    by_s: dict | None = None,
) -> PortfolioRiskState:
    return PortfolioRiskState(
        net_delta=0.0,
        net_vega=0.0,
        net_theta=0.0,
        open_position_count=open_count,
        portfolio_value=value,
        positions_by_underlying=by_u or {},
        positions_by_sector=by_s or {},
    )


def _equity(ticker="AAPL", shares=10, entry=150.0, stop=145.0):
    return {
        "ticker": ticker,
        "asset_type": "equity",
        "trade_plan": {"shares": shares, "entry_price": entry, "stop_price": stop},
    }


def _options(ticker="SPY", qty=1, max_loss=350.0):
    return {
        "ticker": ticker,
        "asset_type": "options",
        "strategy": "bull_put_spread",
        "quantity": qty,
        "spread": {"max_loss": max_loss},
    }


def test_estimate_equity_risk_uses_stop_distance():
    assert estimate_proposed_risk_dollars(_equity()) == 50.0  # 5 * 10


def test_estimate_options_risk_uses_max_loss_times_qty():
    assert estimate_proposed_risk_dollars(_options(qty=2, max_loss=350.0)) == 700.0


def test_blocks_max_positions():
    r = evaluate_portfolio_gates(
        _equity(),
        _portfolio(open_count=RiskManager().max_concurrent),
    )
    assert not r.allowed
    assert "max_positions" in r.flags


def test_blocks_underlying_concentration():
    # Already 24k in AAPL; adding $50 keeps under 25% — use large risk instead
    sig = _equity(shares=200, entry=200.0, stop=100.0)  # risk = 20_000
    r = evaluate_portfolio_gates(
        sig,
        _portfolio(by_u={"AAPL": 10_000.0}),  # 10k + 20k = 30% > 25%
    )
    assert not r.allowed
    assert "concentration_limit" in r.flags


def test_blocks_sector_concentration_hard():
    # Technology already at 35k; add 10k AAPL risk → 45% > 40%
    sig = _equity(shares=100, entry=200.0, stop=100.0)  # 10_000
    r = evaluate_portfolio_gates(
        sig,
        _portfolio(by_s={"Technology": 35_000.0}, by_u={"MSFT": 35_000.0}),
    )
    assert not r.allowed
    assert "sector_concentration_limit" in r.flags


def test_blocks_projected_heat_high():
    # Diversified underlyings so sector/underlying caps don't fire first.
    # Open risk 45k across Index + new 10k equity in Bonds bucket → heat 55%.
    sig = {
        "ticker": "TLT",
        "asset_type": "equity",
        "trade_plan": {"shares": 100, "entry_price": 200.0, "stop_price": 100.0},
    }
    r = evaluate_portfolio_gates(
        sig,
        _portfolio(by_u={"SPY": 45_000.0}, by_s={"Index": 45_000.0}),
    )
    assert not r.allowed
    assert "portfolio_heat_high" in r.flags


def test_allows_clean_trade():
    r = evaluate_portfolio_gates(_equity(), _portfolio())
    assert r.allowed
    assert r.proposed_risk_dollars == 50.0


def test_greeks_off_by_default_even_if_delta_huge():
    sig = _options()
    sig["delta"] = 1.0
    r = evaluate_portfolio_gates(sig, _portfolio(), enforce_greeks=False)
    assert r.allowed


def test_greeks_block_when_enforced():
    sig = _options()
    sig["delta"] = 0.25
    r = evaluate_portfolio_gates(
        sig,
        PortfolioRiskState(
            net_delta=0.20,
            net_vega=0.0,
            net_theta=0.0,
            open_position_count=0,
            portfolio_value=100_000.0,
            positions_by_underlying={},
            positions_by_sector={},
        ),
        enforce_greeks=True,
    )
    assert not r.allowed
    assert "delta_limit" in r.flags


@pytest.mark.asyncio
async def test_execute_signal_blocks_on_portfolio_gate():
    try:
        from app.api.routes.trade_desk import _execute_signal
    except Exception as exc:
        pytest.skip(f"trade_desk import unavailable on this Python: {exc}")

    from app.services.guardrails import PortfolioState

    clean = PortfolioState(
        current_value=100_000.0,
        starting_capital=100_000.0,
        daily_pnl=0.0,
        weekly_pnl=0.0,
        monthly_pnl=0.0,
        consecutive_losses=0,
        trades_today=0,
    )
    broker = MagicMock()
    broker.place_equity_order = AsyncMock()

    blocked = PortfolioGateResult(
        allowed=False,
        reason="Single underlying concentration: AAPL would be 40.0% of portfolio (max 25%)",
        flags=["concentration_limit"],
        proposed_risk_dollars=5000.0,
    )

    with patch("app.utils.market_hours.is_market_open", return_value=True), \
         patch("app.api.routes.trade_desk._fetch_portfolio_state", new=AsyncMock(return_value=clean)), \
         patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False), \
         patch(
             "app.services.execution_portfolio_gate.check_execution_portfolio",
             new=AsyncMock(return_value=blocked),
         ), \
         patch("app.broker.broker_factory.get_broker", return_value=broker):
        result = await _execute_signal(
            {
                "id": "s1",
                "ticker": "AAPL",
                "action": "BUY",
                "asset_type": "equity",
                "confidence": 0.95,
                "trade_plan": {
                    "shares": 10,
                    "entry_price": 150.0,
                    "stop_price": 145.0,
                    "risk_reward": 2.0,
                },
                "indicators": {"volume_ratio": 1.5},
                "signal_score": 0.8,
            },
            approved_by="autopilot",
        )

    assert result["result"] == "blocked"
    assert "portfolio_gate" in result["reason"]
    broker.place_equity_order.assert_not_called()


@pytest.mark.asyncio
async def test_check_disabled_via_settings(monkeypatch):
    from app.core.config import settings
    from app.services.execution_portfolio_gate import check_execution_portfolio

    monkeypatch.setattr(settings, "execution_portfolio_gate", False)
    r = await check_execution_portfolio(_equity(), 100_000.0)
    assert r.allowed
    assert "portfolio_gate_disabled" in r.flags
