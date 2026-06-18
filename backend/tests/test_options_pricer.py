"""
Unit tests for BlackScholesPricer.
Reference values computed from the standard Black-Scholes formula.
All assertions use 0.01 tolerance as specified in Task 1.10.
Run with: pytest tests/test_options_pricer.py -v
"""

import math
import pytest
from app.services.options_pricer import BlackScholesPricer

pricer = BlackScholesPricer()
TOLERANCE = 0.01

# Reference SPY inputs
S = 450.0   # SPY price
K = 450.0   # ATM strike
T = 30/365  # 30 DTE
r = 0.05    # 5% risk-free rate
sigma = 0.20  # 20% IV


class TestCallPrice:
    def test_atm_call_price(self):
        price = pricer.call_price(S, K, T, r, sigma)
        assert price == pytest.approx(11.22, abs=TOLERANCE)

    def test_itm_call_greater_than_atm(self):
        itm = pricer.call_price(S, K - 10, T, r, sigma)
        atm = pricer.call_price(S, K, T, r, sigma)
        assert itm > atm

    def test_call_price_at_expiry_otm(self):
        assert pricer.call_price(S=450, K=460, T=0, r=r, sigma=sigma) == pytest.approx(0.0)

    def test_call_price_at_expiry_itm(self):
        assert pricer.call_price(S=460, K=450, T=0, r=r, sigma=sigma) == pytest.approx(10.0)

    def test_call_price_positive(self):
        assert pricer.call_price(S, K, T, r, sigma) > 0


class TestPutPrice:
    def test_atm_put_price(self):
        price = pricer.put_price(S, K, T, r, sigma)
        assert price == pytest.approx(9.37, abs=TOLERANCE)

    def test_put_call_parity(self):
        call = pricer.call_price(S, K, T, r, sigma)
        put = pricer.put_price(S, K, T, r, sigma)
        # C - P = S - K*e^(-rT)
        lhs = call - put
        rhs = S - K * math.exp(-r * T)
        assert lhs == pytest.approx(rhs, abs=TOLERANCE)

    def test_put_price_at_expiry_otm(self):
        assert pricer.put_price(S=460, K=450, T=0, r=r, sigma=sigma) == pytest.approx(0.0)

    def test_put_price_at_expiry_itm(self):
        assert pricer.put_price(S=440, K=450, T=0, r=r, sigma=sigma) == pytest.approx(10.0)


class TestDelta:
    def test_atm_call_delta_near_half(self):
        d = pricer.delta(S, K, T, r, sigma, "call")
        assert 0.45 < d < 0.60

    def test_atm_put_delta_near_neg_half(self):
        d = pricer.delta(S, K, T, r, sigma, "put")
        assert -0.60 < d < -0.45

    def test_deep_itm_call_delta_near_one(self):
        d = pricer.delta(S, K=300, T=T, r=r, sigma=sigma, option_type="call")
        assert d > 0.95

    def test_deep_otm_call_delta_near_zero(self):
        d = pricer.delta(S, K=600, T=T, r=r, sigma=sigma, option_type="call")
        assert d < 0.05

    def test_call_delta_minus_put_delta_near_one(self):
        call_d = pricer.delta(S, K, T, r, sigma, "call")
        put_d = pricer.delta(S, K, T, r, sigma, "put")
        assert call_d - put_d == pytest.approx(1.0, abs=0.02)


class TestGamma:
    def test_gamma_positive(self):
        g = pricer.gamma(S, K, T, r, sigma)
        assert g > 0

    def test_gamma_higher_atm_than_otm(self):
        atm = pricer.gamma(S, K=S, T=T, r=r, sigma=sigma)
        otm = pricer.gamma(S, K=S + 30, T=T, r=r, sigma=sigma)
        assert atm > otm

    def test_gamma_at_expiry_zero(self):
        assert pricer.gamma(S, K, T=0, r=r, sigma=sigma) == pytest.approx(0.0)


class TestTheta:
    def test_theta_negative_long_call(self):
        t = pricer.theta(S, K, T, r, sigma, "call")
        assert t < 0

    def test_theta_negative_long_put(self):
        t = pricer.theta(S, K, T, r, sigma, "put")
        assert t < 0

    def test_theta_at_expiry_zero(self):
        assert pricer.theta(S, K, T=0, r=r, sigma=sigma, option_type="call") == pytest.approx(0.0)

    def test_theta_magnitude_reasonable(self):
        # 30 DTE ATM option: daily decay should be a modest negative per-share value.
        t = pricer.theta(S, K, T, r, sigma, "call")
        assert -0.25 < t < -0.01


class TestVega:
    def test_vega_positive(self):
        v = pricer.vega(S, K, T, r, sigma)
        assert v > 0

    def test_vega_higher_atm_than_otm(self):
        atm = pricer.vega(S, K=S, T=T, r=r, sigma=sigma)
        otm = pricer.vega(S, K=S + 30, T=T, r=r, sigma=sigma)
        assert atm > otm

    def test_vega_at_expiry_zero(self):
        assert pricer.vega(S, K, T=0, r=r, sigma=sigma) == pytest.approx(0.0)


class TestImpliedVol:
    def test_iv_round_trips_call(self):
        """IV solver should recover the input sigma from a BS price."""
        market = pricer.call_price(S, K, T, r, sigma)
        iv = pricer.implied_vol(market, S, K, T, r, "call")
        assert iv == pytest.approx(sigma, abs=0.001)

    def test_iv_round_trips_put(self):
        market = pricer.put_price(S, K, T, r, sigma)
        iv = pricer.implied_vol(market, S, K, T, r, "put")
        assert iv == pytest.approx(sigma, abs=0.001)

    def test_higher_price_gives_higher_iv(self):
        base = pricer.call_price(S, K, T, r, sigma=0.20)
        high = pricer.call_price(S, K, T, r, sigma=0.35)
        iv_base = pricer.implied_vol(base, S, K, T, r, "call")
        iv_high = pricer.implied_vol(high, S, K, T, r, "call")
        assert iv_high > iv_base

    def test_expired_option_raises(self):
        with pytest.raises(ValueError, match="T <= 0"):
            pricer.implied_vol(5.0, S, K, T=0, r=r, option_type="call")
