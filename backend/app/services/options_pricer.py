"""
Black-Scholes options pricer with full Greeks and implied volatility.
All inputs and outputs are typed. Used in backtesting and signal scoring.
"""

import math
import logging
from scipy.optimize import brentq
from scipy.stats import norm

logger = logging.getLogger(__name__)

# Numerical tolerance for IV convergence
IV_TOLERANCE = 1e-6
IV_MIN = 0.0001
IV_MAX = 20.0   # 2000% IV upper bound (handles extreme events)


class BlackScholesPricer:
    """
    Closed-form Black-Scholes pricer for European options.

    All methods are stateless — call directly or instantiate for convenience.

    Args (shared across methods):
        S:           Current underlying price
        K:           Strike price
        T:           Time to expiration in years (e.g. 30 days = 30/365)
        r:           Risk-free rate as decimal (e.g. 0.05 = 5%)
        sigma:       Implied volatility as decimal (e.g. 0.25 = 25%)
        option_type: "call" or "put"
    """

    @staticmethod
    def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Internal d1 calculation. T must be > 0."""
        return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))

    @staticmethod
    def _d2(d1: float, sigma: float, T: float) -> float:
        return d1 - sigma * math.sqrt(T)

    # ── Prices ───────────────────────────────────────────────────────────────

    def call_price(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Black-Scholes European call price."""
        if T <= 0:
            return max(S - K, 0.0)
        d1 = self._d1(S, K, T, r, sigma)
        d2 = self._d2(d1, sigma, T)
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)

    def put_price(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Black-Scholes European put price (via put-call parity)."""
        if T <= 0:
            return max(K - S, 0.0)
        return self.call_price(S, K, T, r, sigma) - S + K * math.exp(-r * T)

    # ── Greeks ───────────────────────────────────────────────────────────────

    def delta(
        self, S: float, K: float, T: float, r: float, sigma: float, option_type: str
    ) -> float:
        """
        Delta: rate of change of option price with respect to underlying price.
        Call delta: 0 to 1. Put delta: -1 to 0.
        """
        if T <= 0:
            if option_type == "call":
                return 1.0 if S > K else 0.0
            return -1.0 if S < K else 0.0

        d1 = self._d1(S, K, T, r, sigma)
        if option_type == "call":
            return norm.cdf(d1)
        return norm.cdf(d1) - 1

    def gamma(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """
        Gamma: rate of change of delta. Same for calls and puts.
        High gamma near expiry or ATM.
        """
        if T <= 0:
            return 0.0
        d1 = self._d1(S, K, T, r, sigma)
        return norm.pdf(d1) / (S * sigma * math.sqrt(T))

    def theta(
        self, S: float, K: float, T: float, r: float, sigma: float, option_type: str
    ) -> float:
        """
        Theta: daily time decay (returned as per-day, not annualized).
        Almost always negative for long options.
        """
        if T <= 0:
            return 0.0
        d1 = self._d1(S, K, T, r, sigma)
        d2 = self._d2(d1, sigma, T)

        common = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))

        if option_type == "call":
            annual = common - r * K * math.exp(-r * T) * norm.cdf(d2)
        else:
            annual = common + r * K * math.exp(-r * T) * norm.cdf(-d2)

        return annual / 365  # Convert to per-day theta

    def vega(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """
        Vega: sensitivity to a 1% change in implied volatility.
        Returned as dollar change per 1% IV move (divided by 100).
        """
        if T <= 0:
            return 0.0
        d1 = self._d1(S, K, T, r, sigma)
        return S * norm.pdf(d1) * math.sqrt(T) / 100  # Per 1% IV change

    # ── Implied Volatility ────────────────────────────────────────────────────

    def implied_vol(
        self,
        market_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        option_type: str,
    ) -> float:
        """
        Solve for implied volatility via Brent's method.
        Returns IV as a decimal (e.g. 0.25 = 25%).
        Raises ValueError if no solution found in IV range.

        Args:
            market_price: Current market price (mid of bid/ask)
            S, K, T, r:  Standard BS inputs
            option_type: "call" or "put"
        """
        if T <= 0:
            raise ValueError("Cannot calculate IV for expired option (T <= 0)")

        if option_type == "call":
            intrinsic = max(S - K * math.exp(-r * T), 0.0)
        else:
            intrinsic = max(K * math.exp(-r * T) - S, 0.0)

        if market_price < intrinsic:
            raise ValueError(
                f"Market price {market_price} is below intrinsic value {intrinsic:.4f}"
            )

        def objective(sigma: float) -> float:
            if option_type == "call":
                return self.call_price(S, K, T, r, sigma) - market_price
            return self.put_price(S, K, T, r, sigma) - market_price

        try:
            iv = brentq(objective, IV_MIN, IV_MAX, xtol=IV_TOLERANCE, maxiter=500)
        except ValueError as exc:
            raise ValueError(
                f"IV solver failed for {option_type} S={S} K={K} T={T:.4f} "
                f"market_price={market_price}: {exc}"
            ) from exc

        return round(iv, 6)
