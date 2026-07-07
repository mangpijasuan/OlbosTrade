"""Tests for the Options Decision Engine (EV-ranked vertical selection)."""

from __future__ import annotations

import pytest

from app.services.options_decision_engine import (
    evaluate_vertical, kelly_fraction, trade_score, decide,
)


# ── evaluate_vertical — deterministic economics ────────────────────────────────
def test_bull_put_credit_economics():
    r = evaluate_vertical(kind="bull_put", spot=750, short_strike=745,
                          long_strike=740, net_price=1.50, dte=4, iv=0.20)
    assert r["type"] == "CREDIT"
    assert r["max_gain"] == 150.0            # credit × 100
    assert r["max_loss"] == 350.0            # (width 5 − 1.5) × 100
    assert r["breakeven"] == 743.5           # short − credit
    assert r["risk_reward"] == round(150 / 350, 4)
    assert 0.0 < r["pop"] < 1.0


def test_bear_call_credit_economics():
    r = evaluate_vertical(kind="bear_call", spot=750, short_strike=750,
                          long_strike=755, net_price=1.50, dte=4, iv=0.20)
    assert r["max_gain"] == 150.0 and r["max_loss"] == 350.0
    assert r["breakeven"] == 751.5           # short + credit
    assert 0.0 < r["pop"] < 1.0


def test_bull_call_debit_economics():
    r = evaluate_vertical(kind="bull_call", spot=750, short_strike=750,
                          long_strike=745, net_price=2.0, dte=4, iv=0.20)
    assert r["type"] == "DEBIT"
    assert r["max_gain"] == 300.0            # (width 5 − 2) × 100
    assert r["max_loss"] == 200.0            # debit × 100
    assert r["breakeven"] == 747.0           # long + debit
    assert 0.0 < r["pop"] < 1.0


def test_bear_put_debit_economics():
    r = evaluate_vertical(kind="bear_put", spot=750, short_strike=745,
                          long_strike=750, net_price=2.0, dte=4, iv=0.20)
    assert r["max_gain"] == 300.0 and r["max_loss"] == 200.0
    assert r["breakeven"] == 748.0           # long − debit


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        evaluate_vertical(kind="butterfly", spot=750, short_strike=745,
                          long_strike=740, net_price=1.0, dte=4, iv=0.2)


def test_degenerate_inputs_do_not_crash():
    r = evaluate_vertical(kind="bull_put", spot=0, short_strike=745,
                          long_strike=740, net_price=1.5, dte=0, iv=0.0)
    assert r["pop"] == 0.0   # no time/vol → probability floors at 0


# ── kelly_fraction ─────────────────────────────────────────────────────────────
def test_kelly_negative_edge_floors_at_zero():
    # p=0.7, b=150/350 → f = 0.7 − 0.3/0.4286 = 0 → floored
    assert kelly_fraction(0.7, 150, 350) == 0.0


def test_kelly_capped():
    # p=0.8, b=1.5 → f≈0.667 → capped at 0.25
    assert kelly_fraction(0.8, 300, 200) == 0.25


def test_kelly_zero_when_no_gain_or_loss():
    assert kelly_fraction(0.9, 0, 100) == 0.0
    assert kelly_fraction(0.9, 100, 0) == 0.0


# ── trade_score ────────────────────────────────────────────────────────────────
def test_trade_score_blend_and_bounds():
    s = trade_score(pop=0.78, expected_value=32, risk_reward=2.0, confidence=0.6)
    assert s == 85          # 0.4*.78 + .25*1 + .2*1 + .15*.6 = .852
    assert 0 <= trade_score(pop=0, expected_value=-1, risk_reward=0, confidence=0) <= 100


# ── decide — ranking + NO-TRADE gate ───────────────────────────────────────────
def _cand(kind, ev, pop, rr=1.0):
    return {"kind": kind, "short_strike": 745, "long_strike": 740,
            "expected_value": ev, "pop": pop, "risk_reward": rr}


def test_decide_picks_highest_ev_direction_appropriate():
    cands = [_cand("bull_put", ev=20, pop=0.75), _cand("bull_call", ev=45, pop=0.65),
             _cand("bear_call", ev=99, pop=0.9)]   # bearish — must be excluded
    d = decide(cands, direction="BULLISH", confidence=0.7, min_pop=0.5)
    assert d.decision == "TRADE"
    assert d.best["kind"] == "bull_call" and d.best["expected_value"] == 45
    assert d.trade_score > 0


def test_decide_no_trade_when_ev_below_min():
    cands = [_cand("bull_put", ev=-5, pop=0.8)]
    d = decide(cands, direction="BULLISH", confidence=0.9, min_ev=0.0)
    assert d.decision == "NO_TRADE" and any("EV" in r for r in d.reasoning)


def test_decide_no_trade_when_pop_below_min():
    cands = [_cand("bull_put", ev=50, pop=0.40)]
    d = decide(cands, direction="BULLISH", confidence=0.9, min_pop=0.55)
    assert d.decision == "NO_TRADE" and any("POP" in r for r in d.reasoning)


def test_decide_no_trade_low_confidence():
    cands = [_cand("bull_put", ev=50, pop=0.8)]
    d = decide(cands, direction="BULLISH", confidence=0.10, min_confidence=0.5)
    assert d.decision == "NO_TRADE" and any("confidence" in r for r in d.reasoning)


def test_decide_neutral_direction_stays_cash():
    d = decide([_cand("bull_put", 50, 0.8)], direction="NEUTRAL", confidence=0.9)
    assert d.decision == "NO_TRADE"


def test_decide_no_candidates_for_direction():
    d = decide([_cand("bear_call", 50, 0.8)], direction="BULLISH", confidence=0.9)
    assert d.decision == "NO_TRADE"


def test_decision_to_dict_roundtrips():
    d = decide([_cand("bull_put", ev=30, pop=0.75, rr=1.5)],
               direction="BULLISH", confidence=0.7)
    out = d.to_dict()
    assert out["decision"] == "TRADE" and out["best"]["kind"] == "bull_put"


def test_decide_no_trade_low_risk_reward():
    cands = [_cand("bull_put", ev=50, pop=0.8, rr=0.1)]   # R:R below min
    d = decide(cands, direction="BULLISH", confidence=0.9, min_rr=0.25)
    assert d.decision == "NO_TRADE" and any("R:R" in r for r in d.reasoning)
