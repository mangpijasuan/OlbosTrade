"""
Guardrail Engine tests — minimum 15 pytest tests covering every edge case.
Run with: pytest tests/test_guardrails.py -v
"""

from datetime import datetime, timedelta, timezone
import pytest
from app.services.guardrails import GuardrailEngine, PortfolioState


def make_portfolio(**kwargs) -> PortfolioState:
    defaults = dict(
        current_value=25000.0,
        starting_capital=25000.0,
        daily_pnl=0.0,
        weekly_pnl=0.0,
        monthly_pnl=0.0,
        consecutive_losses=0,
        trades_today=0,
        cooling_off_until=None,
    )
    defaults.update(kwargs)
    return PortfolioState(**defaults)


@pytest.fixture
def engine():
    return GuardrailEngine()


# ── Normal conditions ─────────────────────────────────────────────────────────

def test_clean_portfolio_trading_allowed(engine):
    status = engine.check_all(make_portfolio())
    assert status.trading_allowed is True
    assert status.trading_mode == "normal"


def test_small_daily_loss_allowed(engine):
    status = engine.check_all(make_portfolio(daily_pnl=-100))
    assert status.trading_allowed is True


# ── Daily loss limit ──────────────────────────────────────────────────────────

def test_daily_loss_limit_exact_triggers(engine):
    """At exactly -2% daily loss, trading must stop."""
    pnl = -25000 * 0.02
    status = engine.check_all(make_portfolio(daily_pnl=pnl))
    assert status.trading_allowed is False
    assert "daily_loss_limit" in status.flags


def test_daily_loss_limit_over_triggers(engine):
    pnl = -25000 * 0.025
    status = engine.check_all(make_portfolio(daily_pnl=pnl))
    assert status.trading_allowed is False
    assert status.suspended_until is not None


def test_daily_loss_suspends_for_cooling_off_hours(engine):
    pnl = -25000 * 0.021
    status = engine.check_all(make_portfolio(daily_pnl=pnl))
    assert status.trading_allowed is False
    now = datetime.now(timezone.utc)
    assert status.suspended_until > now + timedelta(hours=20)


# ── Weekly loss limit ─────────────────────────────────────────────────────────

def test_weekly_loss_limit_triggers(engine):
    pnl = -25000 * 0.05
    status = engine.check_all(make_portfolio(weekly_pnl=pnl))
    assert status.trading_allowed is False
    assert "weekly_loss_limit" in status.flags


def test_weekly_loss_suspends_3_days(engine):
    pnl = -25000 * 0.06
    status = engine.check_all(make_portfolio(weekly_pnl=pnl))
    assert status.trading_allowed is False
    now = datetime.now(timezone.utc)
    assert status.suspended_until > now + timedelta(days=2)


# ── Monthly loss limit ────────────────────────────────────────────────────────

def test_monthly_loss_limit_triggers(engine):
    pnl = -25000 * 0.10
    status = engine.check_all(make_portfolio(monthly_pnl=pnl))
    assert status.trading_allowed is False
    assert "monthly_loss_limit" in status.flags


def test_monthly_loss_suspends_30_days(engine):
    pnl = -25000 * 0.11
    status = engine.check_all(make_portfolio(monthly_pnl=pnl))
    assert status.trading_allowed is False
    now = datetime.now(timezone.utc)
    assert status.suspended_until > now + timedelta(days=25)


# ── Consecutive losses ────────────────────────────────────────────────────────

def test_consecutive_losses_limit_triggers(engine):
    status = engine.check_all(make_portfolio(consecutive_losses=3))
    assert status.trading_allowed is False
    assert "consecutive_loss_limit" in status.flags


def test_two_consecutive_losses_allowed(engine):
    status = engine.check_all(make_portfolio(consecutive_losses=2))
    assert status.trading_allowed is True


def test_consecutive_losses_suspends_48h(engine):
    status = engine.check_all(make_portfolio(consecutive_losses=3))
    now = datetime.now(timezone.utc)
    assert status.suspended_until > now + timedelta(hours=44)


# ── Cooling off period ────────────────────────────────────────────────────────

def test_active_cooling_off_blocks_trading(engine):
    future = datetime.now(timezone.utc) + timedelta(hours=12)
    status = engine.check_all(make_portfolio(cooling_off_until=future))
    assert status.trading_allowed is False


def test_expired_cooling_off_allows_trading(engine):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    status = engine.check_all(make_portfolio(cooling_off_until=past))
    assert status.trading_allowed is True


# ── Daily trade cap ───────────────────────────────────────────────────────────

def test_trade_cap_blocks_at_limit(engine):
    status = engine.check_all(make_portfolio(trades_today=3))
    assert status.trading_allowed is False
    assert "daily_trade_cap" in status.flags


def test_trade_cap_allows_below_limit(engine):
    status = engine.check_all(make_portfolio(trades_today=2))
    assert status.trading_allowed is True


# ── Capital preservation mode ─────────────────────────────────────────────────

def test_capital_preservation_mode_activates_at_threshold(engine):
    status = engine.check_all(make_portfolio(current_value=25000 * 0.85))
    assert status.trading_allowed is True
    assert status.trading_mode == "capital_preservation"
    assert "capital_preservation_mode" in status.flags


def test_capital_preservation_above_threshold_is_normal(engine):
    status = engine.check_all(make_portfolio(current_value=25000 * 0.86))
    assert status.trading_mode == "normal"


def test_capital_preservation_blocks_iron_condor(engine):
    status = engine.check_all(make_portfolio(current_value=25000 * 0.80))
    assert not engine.is_strategy_allowed("iron_condor", status)
    assert not engine.is_strategy_allowed("bull_call_debit_spread", status)


def test_capital_preservation_allows_credit_spreads(engine):
    status = engine.check_all(make_portfolio(current_value=25000 * 0.80))
    assert engine.is_strategy_allowed("bull_put_spread", status)
    assert engine.is_strategy_allowed("bear_call_spread", status)


def test_capital_preservation_halves_position_size(engine):
    status = engine.check_all(make_portfolio(current_value=25000 * 0.80))
    assert engine.get_position_size_multiplier(status) == 0.50


def test_normal_mode_full_position_size(engine):
    status = engine.check_all(make_portfolio())
    assert engine.get_position_size_multiplier(status) == 1.0


def test_capital_preservation_raises_signal_threshold(engine):
    status = engine.check_all(make_portfolio(current_value=25000 * 0.80))
    threshold = engine.get_signal_threshold(status)
    from app.core.config import settings
    assert threshold == settings.signal_score_preservation_mode


# ── Priority ordering ─────────────────────────────────────────────────────────

def test_cooling_off_takes_priority_over_daily_loss(engine):
    """Cooling off should be evaluated before other limits."""
    future = datetime.now(timezone.utc) + timedelta(hours=6)
    status = engine.check_all(make_portfolio(
        cooling_off_until=future,
        daily_pnl=-25000 * 0.021,
    ))
    assert status.trading_allowed is False
    assert "cooling_off_active" in status.flags
