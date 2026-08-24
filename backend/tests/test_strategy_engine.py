"""Tests for strategy_engine — signals, sizing, exits, and approve_trade gate."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from app.services.guardrails import GuardrailEngine, PortfolioState
from app.services.risk_manager import PortfolioRiskState, RiskManager
from app.services.strategy_engine import (
    BullPutSpread, BearCallSpread, IronCondor, BullCallDebitSpread,
    StrategyExitParams, approve_trade, Signal, _active_risk_pct,
)


def _opt(strike, delta):
    return NS(strike=strike, greeks=NS(delta=delta))


def _chain(price=450.0, puts=None, calls=None):
    return NS(
        underlying="SPY", expiration=date(2025, 6, 20), underlying_price=price,
        puts=puts if puts is not None else [_opt(440, -0.15), _opt(445, -0.20), _opt(450, -0.30)],
        calls=calls if calls is not None else [_opt(450, 0.30), _opt(455, 0.20), _opt(460, 0.15)],
    )


def _clean():
    return PortfolioState(current_value=100000, starting_capital=100000,
                          daily_pnl=Decimal("0"), weekly_pnl=Decimal("0"),
                          monthly_pnl=Decimal("0"), consecutive_losses=0, trades_today=0)


def _preservation():
    return PortfolioState(current_value=80000, starting_capital=100000,
                          daily_pnl=Decimal("0"), weekly_pnl=Decimal("0"),
                          monthly_pnl=Decimal("0"), consecutive_losses=0, trades_today=0)


def _risk():
    return PortfolioRiskState(net_delta=0, net_vega=0, net_theta=0, open_position_count=0,
                              portfolio_value=100000, positions_by_underlying={}, positions_by_sector={})


def test_active_risk_pct_returns_float():
    assert isinstance(_active_risk_pct(), float)


def test_find_strike_skips_contracts_without_greeks():
    chain = _chain(puts=[NS(strike=445, greeks=None), _opt(450, -0.20)])
    s = BullPutSpread().generate_signal(chain, 40, 50, 20, True, 18, _clean())
    assert s.entry_allowed and s.short_strike == 450.0   # greeks=None contract skipped


# ── Bull Put Spread ──────────────────────────────────────────────────────────
def test_bull_put_happy_path():
    s = BullPutSpread().generate_signal(_chain(), 40, 50, 20, True, 18, _clean())
    assert s.entry_allowed and s.short_strike == 445.0 and s.long_strike == 435.0


@pytest.mark.parametrize("kw,expect", [
    (dict(iv_rank=2), "IV rank too low"),
    (dict(above_sma20=False), "below 20-day SMA"),
    (dict(rsi=40), "RSI too weak"),
])
def test_bull_put_rejections(kw, expect):
    base = dict(chain=_chain(), iv_rank=40, rsi=50, adx=20, above_sma20=True, vix=18,
                portfolio_state=_clean())
    base.update(kw)
    s = BullPutSpread().generate_signal(base["chain"], base["iv_rank"], base["rsi"],
                                        base["adx"], base["above_sma20"], base["vix"],
                                        base["portfolio_state"])
    assert not s.entry_allowed and expect in s.reason


def test_bull_put_no_strike():
    s = BullPutSpread().generate_signal(_chain(puts=[]), 40, 50, 20, True, 18, _clean())
    assert not s.entry_allowed and "0.20 delta put" in s.reason


def test_bull_put_size_and_exit():
    bp = BullPutSpread()
    sz = bp.size_position(Signal("bull_put_spread", "SPY", "bullish", True, "ok"),
                          _risk(), bp.guardrails.check_all(_clean()))
    assert sz.contracts >= 0 and sz.risk_per_contract == 1000
    assert bp.check_exit(2.0, 0.9, 30, False).should_exit          # 50%+ profit
    assert bp.check_exit(2.0, 2.0, 15, False).should_exit          # DTE stop
    assert bp.check_exit(2.0, 4.0, 30, False).urgency == "immediate"  # 2x loss
    assert not bp.check_exit(2.0, 1.5, 30, False).should_exit


# ── StrategyExitParams: default-preserving + override behavior (Track 2D) ────

@pytest.mark.parametrize("strategy_cls,entry_credit,at_default_target", [
    (BullPutSpread, 2.0, 0.9),          # 50% target: profit_pct=(2-0.9)/2=0.55 >= 0.50
    (BearCallSpread, 2.0, 0.9),         # 50% target, same shape
    (IronCondor, 2.0, 1.4),             # 25% target: profit_pct=(2-1.4)/2=0.30 >= 0.25
])
def test_no_args_matches_explicit_default_params(strategy_cls, entry_credit, at_default_target):
    """BullPutSpread() (no args) must produce identical decisions to
    BullPutSpread(StrategyExitParams()) constructed with THIS strategy's
    own DEFAULT_PARAMS — proves the params refactor changed nothing for
    the live/default path (each strategy has its own defaults; a bare
    StrategyExitParams() alone is NOT a safe stand-in for every strategy,
    see test_bull_call_debit_default_differs_from_shared_default below)."""
    no_args = strategy_cls()
    explicit = strategy_cls(strategy_cls.DEFAULT_PARAMS)
    a = no_args.check_exit(entry_credit, at_default_target, 30, False)
    b = explicit.check_exit(entry_credit, at_default_target, 30, False)
    assert a.should_exit == b.should_exit
    assert a.reason == b.reason


def test_bull_call_debit_default_differs_from_shared_default():
    """Confirms the real bug this session caught: BullCallDebitSpread's own
    hardcoded values (75% profit / 10 DTE) differ from BaseStrategy's
    shared StrategyExitParams() default (50% / 21) — passing a bare
    StrategyExitParams() to it would silently change its live behavior."""
    assert BullCallDebitSpread.DEFAULT_PARAMS.profit_target_pct == 0.75
    assert BullCallDebitSpread.DEFAULT_PARAMS.dte_exit == 10
    assert StrategyExitParams().profit_target_pct == 0.50


def test_custom_params_change_check_exit_at_the_boundary():
    """A non-default profit_target_pct changes check_exit()'s decision
    exactly where the old hardcoded 0.50 used to draw the line."""
    entry_credit, current_value = 2.0, 1.3  # profit_pct = 0.35
    default_bp = BullPutSpread()
    assert not default_bp.check_exit(entry_credit, current_value, 30, False).should_exit

    tighter_bp = BullPutSpread(StrategyExitParams(profit_target_pct=0.35))
    assert tighter_bp.check_exit(entry_credit, current_value, 30, False).should_exit


# ── Bear Call Spread ─────────────────────────────────────────────────────────
def test_bear_call_happy_and_rejections():
    s = BearCallSpread().generate_signal(_chain(), 40, 50, 20, False, 18, _clean())
    assert s.entry_allowed and s.short_strike == 455.0
    assert not BearCallSpread().generate_signal(_chain(), 2, 50, 20, False, 18, _clean()).entry_allowed
    assert not BearCallSpread().generate_signal(_chain(), 40, 50, 20, True, 18, _clean()).entry_allowed   # above sma
    assert not BearCallSpread().generate_signal(_chain(), 40, 70, 20, False, 18, _clean()).entry_allowed  # rsi
    assert not BearCallSpread().generate_signal(_chain(calls=[]), 40, 50, 20, False, 18, _clean()).entry_allowed


def test_bear_call_iv_rank_threshold_matches_docstring():
    """The docstring says "IV rank > 30", but the entry check only rejected
    below 5 — a bear_call_spread would enter selling calls at IV rank 10-29,
    collecting thin credit for the risk taken. Confirmed in a walk-forward
    backtest: bear_call_spread lost money in every calendar year 2015-2025
    (bull_put_spread, the identical exit-rule mirror strategy, was
    profitable most years) — a low IV bar was part of why the credit
    collected didn't compensate for the risk of a short call getting run
    over by a snapback rally."""
    # IV rank 29 — below the documented >30 bar, must now be rejected.
    below = BearCallSpread().generate_signal(_chain(), 29, 50, 20, False, 18, _clean())
    assert not below.entry_allowed
    assert "need >30" in below.reason
    # IV rank 30 — clears the bar (matches the sibling strategies' "< threshold"
    # rejection idiom used throughout this file, e.g. BullPutSpread's "need >5"
    # also technically passes at exactly 5).
    at_bar = BearCallSpread().generate_signal(_chain(), 30, 50, 20, False, 18, _clean())
    assert at_bar.entry_allowed
    # Old behavior for reference: IV rank 10 used to pass (old bar was >5);
    # under the fixed threshold it must now be rejected.
    old_threshold_gap = BearCallSpread().generate_signal(_chain(), 10, 50, 20, False, 18, _clean())
    assert not old_threshold_gap.entry_allowed


def test_bear_call_size_and_exit():
    bc = BearCallSpread()
    sz = bc.size_position(Signal("bear_call_spread", "SPY", "bearish", True, "ok"),
                          _risk(), bc.guardrails.check_all(_clean()))
    assert sz.risk_per_contract == 1000
    assert bc.check_exit(2.0, 0.5, 30, False).should_exit
    assert bc.check_exit(2.0, 2.0, 15, False).should_exit
    assert bc.check_exit(2.0, 5.0, 30, False).urgency == "immediate"
    assert not bc.check_exit(2.0, 1.8, 30, False).should_exit


# ── Iron Condor ──────────────────────────────────────────────────────────────
def test_iron_condor_happy_and_rejections():
    s = IronCondor().generate_signal(_chain(), 50, 50, 15, True, 18, _clean())
    assert s.entry_allowed and s.short_strike == 440.0 and s.short_strike_2 == 460.0
    assert not IronCondor().generate_signal(_chain(), 2, 50, 15, True, 18, _clean()).entry_allowed   # iv
    assert not IronCondor().generate_signal(_chain(), 50, 50, 25, True, 18, _clean()).entry_allowed  # adx
    assert not IronCondor().generate_signal(_chain(), 50, 50, 15, True, 30, _clean()).entry_allowed  # vix
    assert not IronCondor().generate_signal(_chain(puts=[]), 50, 50, 15, True, 18, _clean()).entry_allowed


def test_iron_condor_suspended_in_preservation():
    s = IronCondor().generate_signal(_chain(), 50, 50, 15, True, 18, _preservation())
    assert not s.entry_allowed and "preservation" in s.reason


def test_iron_condor_size_and_exits():
    ic = IronCondor()
    sz = ic.size_position(Signal("iron_condor", "SPY", "neutral", True, "ok"),
                          _risk(), ic.guardrails.check_all(_clean()))
    assert sz.contracts >= 0
    assert ic.check_exit(4.0, 2.9, 30, False).should_exit            # 25% profit
    assert ic.check_exit(4.0, 4.0, 15, False).should_exit            # DTE
    assert ic.check_exit(4.0, 4.0, 30, True).urgency == "immediate"  # put breach
    assert ic.check_exit(4.0, 4.0, 30, False, True).urgency == "immediate"  # call breach
    assert not ic.check_exit(4.0, 3.9, 30, False, False).should_exit


# ── Bull Call Debit Spread ───────────────────────────────────────────────────
def test_debit_happy_and_rejections():
    s = BullCallDebitSpread().generate_signal(_chain(), 20, 60, 20, True, 18, _clean())
    assert s.entry_allowed and s.short_strike == 450.0
    assert not BullCallDebitSpread().generate_signal(_chain(), 100, 60, 20, True, 18, _clean()).entry_allowed  # iv high
    assert not BullCallDebitSpread().generate_signal(_chain(), 20, 60, 20, False, 18, _clean()).entry_allowed  # sma
    assert not BullCallDebitSpread().generate_signal(_chain(), 20, 50, 20, True, 18, _clean()).entry_allowed   # rsi
    assert not BullCallDebitSpread().generate_signal(_chain(calls=[]), 20, 60, 20, True, 18, _clean()).entry_allowed


def test_debit_suspended_in_preservation():
    s = BullCallDebitSpread().generate_signal(_chain(), 20, 60, 20, True, 18, _preservation())
    assert not s.entry_allowed and "preservation" in s.reason


def test_debit_size_and_exit():
    d = BullCallDebitSpread()
    sig = Signal("bull_call_debit_spread", "SPY", "bullish", True, "ok",
                 short_strike=455, long_strike=450)
    sz = d.size_position(sig, _risk(), d.guardrails.check_all(_clean()))
    assert sz.contracts >= 0
    assert d.check_exit(2.0, 3.6, 20, False).should_exit            # 75% profit (debit)
    assert d.check_exit(2.0, 2.0, 5, False).should_exit             # DTE 10
    assert d.check_exit(2.0, 0.9, 20, False).urgency == "immediate" # 50% loss
    assert not d.check_exit(2.0, 2.5, 20, False).should_exit


# ── approve_trade gate ───────────────────────────────────────────────────────
def _sig(strategy="bull_put_spread"):
    return Signal(strategy, "SPY", "bullish", True, "ok")


def test_approve_trade_success():
    ge, rm = GuardrailEngine(), RiskManager()
    ok, msg = approve_trade(_sig(), _clean(), _risk(), 0.99, ge, rm)
    assert ok and "passed" in msg


def test_approve_trade_blocks_low_score():
    ge, rm = GuardrailEngine(), RiskManager()
    ok, msg = approve_trade(_sig(), _clean(), _risk(), 0.01, ge, rm)
    assert not ok and "below threshold" in msg


def test_approve_trade_blocks_strategy_in_preservation():
    ge, rm = GuardrailEngine(), RiskManager()
    ok, msg = approve_trade(_sig("iron_condor"), _preservation(), _risk(), 0.99, ge, rm)
    assert not ok and "not allowed" in msg


def test_approve_trade_blocks_trade_cap():
    ge, rm = GuardrailEngine(), RiskManager()
    state = _clean()
    state.trades_today = 999
    ok, msg = approve_trade(_sig(), state, _risk(), 0.99, ge, rm)
    assert not ok and "trade cap" in msg


def test_approve_trade_blocks_position_count():
    ge, rm = GuardrailEngine(), RiskManager()
    risk = _risk()
    risk.open_position_count = 999
    ok, msg = approve_trade(_sig(), _clean(), risk, 0.99, ge, rm)
    assert not ok and "Max positions" in msg


def test_approve_trade_blocks_guardrail():
    ge, rm = GuardrailEngine(), RiskManager()
    breach = PortfolioState(current_value=90000, starting_capital=100000,
                            daily_pnl=Decimal("-5000"), weekly_pnl=Decimal("-5000"),
                            monthly_pnl=Decimal("-5000"), consecutive_losses=0, trades_today=0)
    ok, msg = approve_trade(_sig(), breach, _risk(), 0.99, ge, rm)
    assert not ok and "Guardrail" in msg
