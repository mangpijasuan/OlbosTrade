"""Tests for the Options Intelligence engine (deterministic, no network)."""

from __future__ import annotations

import pytest

from app.services.options_intelligence import analyze_spread, SpreadIntelligence


def _bull_put(short=430, long=425, spot=450.0, dte=30, iv=0.20, credit=0.6):
    return analyze_spread(spot=spot, short_strike=short, long_strike=long,
                          option_type="put", dte=dte, iv=iv, credit_per_share=credit)


def _bear_call(short=470, long=475, spot=450.0, dte=30, iv=0.20, credit=0.6):
    return analyze_spread(spot=spot, short_strike=short, long_strike=long,
                          option_type="call", dte=dte, iv=iv, credit_per_share=credit)


def test_returns_dataclass_with_all_fields():
    r = _bull_put()
    assert isinstance(r, SpreadIntelligence)
    d = r.as_dict()
    for k in ("pop", "prob_itm_short", "prob_touch_short", "expected_move",
              "delta_short", "expected_value", "kelly_fraction", "reward_risk"):
        assert k in d


def test_otm_bull_put_has_high_pop():
    # Short put 20 below spot → mostly OTM → POP well above 0.5
    r = _bull_put(short=430, spot=450.0)
    assert r.pop > 0.6
    assert 0.0 <= r.prob_itm_short < 0.5


def test_atm_short_pop_near_half():
    r = _bull_put(short=450, long=445, spot=450.0, credit=1.0)
    assert 0.35 < r.pop < 0.65


def test_prob_itm_otm_complementary():
    r = _bull_put()
    assert abs((r.prob_itm_short + r.prob_otm_short) - 1.0) < 1e-9


def test_prob_touch_is_double_itm_capped():
    r = _bull_put()
    assert abs(r.prob_touch_short - min(1.0, 2 * r.prob_itm_short)) < 1e-9
    # deep ITM short → touch caps at 1.0
    deep = analyze_spread(spot=450, short_strike=460, long_strike=455,
                          option_type="put", dte=30, iv=0.20, credit_per_share=0.6)
    assert deep.prob_touch_short <= 1.0


def test_expected_move_scales_with_iv_and_time():
    lo = _bull_put(iv=0.10, dte=30).expected_move
    hi = _bull_put(iv=0.40, dte=30).expected_move
    longer = _bull_put(iv=0.20, dte=60).expected_move
    short = _bull_put(iv=0.20, dte=30).expected_move
    assert hi > lo and longer > short


def test_reward_risk_and_max_pnl():
    r = _bull_put(short=430, long=425, credit=1.0)   # width 5, credit 1 → maxloss 4
    assert r.max_profit == 100.0
    assert r.max_loss == 400.0
    assert abs(r.reward_risk - 0.25) < 1e-6


def test_expected_value_and_kelly_ranges():
    r = _bull_put()
    assert isinstance(r.expected_value, float)
    assert 0.0 <= r.kelly_fraction <= 1.0
    # high-POP, positive-EV trade → positive Kelly
    good = _bull_put(short=420, credit=0.8)
    assert good.pop > 0.7
    if good.expected_value > 0:
        assert good.kelly_fraction > 0


def test_bear_call_symmetry():
    r = _bear_call(short=470, spot=450.0)   # short call above spot → high POP
    assert r.pop > 0.6
    assert r.delta_short >= 0  # call delta non-negative


def test_greeks_present_and_signed():
    r = _bull_put()
    assert r.delta_short <= 0          # short put leg delta is negative
    assert r.theta_short != 0.0


@pytest.mark.parametrize("kwargs", [
    {"spot": 0, "short_strike": 430, "long_strike": 425},
    {"short_strike": -1, "long_strike": 425, "spot": 450},
    {"dte": 0},
    {"iv": 0},
    {"short_strike": 430, "long_strike": 430},   # zero width
])
def test_degenerate_inputs_raise(kwargs):
    base = dict(spot=450.0, short_strike=430, long_strike=425,
                option_type="put", dte=30, iv=0.20, credit_per_share=0.6)
    base.update(kwargs)
    with pytest.raises(ValueError):
        analyze_spread(**base)
