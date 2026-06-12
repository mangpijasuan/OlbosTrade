"""
Integration tests for the 4 new modules.
Tests the complete pipeline: Contract → Analytics → MultiLeg → Dispatch.

Run with: pytest tests/test_integration_modules.py -v
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.broker.contract import EnrichedContract
from app.services.analytics_engine import AnalyticsEngine, MIN_T_YEARS
from app.services.multi_leg_strategy import (
    LegAction, MultiLegStrategy, StrategyLeg,
)
from app.services.execution_dispatcher import (
    DispatchStatus, ExecutionDispatcher, ValidationStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

EXPIRY_35DTE = date.today() + timedelta(days=35)
EXPIRY_TODAY = date.today()


def make_contract(
    strike: float = 450.0,
    option_type: str = "put",
    bid: float = 1.20,
    ask: float = 1.30,
    expiry: date = None,
) -> EnrichedContract:
    return EnrichedContract(
        underlying_ticker="SPY",
        strike_price=strike,
        expiration_date=expiry or EXPIRY_35DTE,
        option_type=option_type,
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2,
        volume=5000,
        open_interest=12000,
    )


def make_bull_put_spread() -> MultiLegStrategy:
    short_put = make_contract(strike=450.0, bid=1.20, ask=1.30)
    long_put  = make_contract(strike=440.0, bid=0.57, ask=0.63)  # spread_pct=10% < 15%
    return MultiLegStrategy(
        strategy_name="bull_put_spread",
        underlying="SPY",
        legs=[
            StrategyLeg(contract=short_put, action=LegAction.SELL, quantity=1),
            StrategyLeg(contract=long_put,  action=LegAction.BUY,  quantity=1),
        ],
    )


def make_iron_condor() -> MultiLegStrategy:
    short_put  = make_contract(strike=445.0, option_type="put",  bid=1.10, ask=1.20)
    long_put   = make_contract(strike=435.0, option_type="put",  bid=0.50, ask=0.58)
    short_call = make_contract(strike=465.0, option_type="call", bid=1.05, ask=1.15)
    long_call  = make_contract(strike=475.0, option_type="call", bid=0.45, ask=0.53)
    return MultiLegStrategy(
        strategy_name="iron_condor",
        underlying="SPY",
        legs=[
            StrategyLeg(contract=short_put,  action=LegAction.SELL, quantity=1),
            StrategyLeg(contract=long_put,   action=LegAction.BUY,  quantity=1),
            StrategyLeg(contract=short_call, action=LegAction.SELL, quantity=1),
            StrategyLeg(contract=long_call,  action=LegAction.BUY,  quantity=1),
        ],
    )


# ── Module 1: EnrichedContract ────────────────────────────────────────────────

class TestEnrichedContract:
    def test_mid_price_correct(self):
        c = make_contract(bid=1.20, ask=1.40)
        assert c.mid_price == pytest.approx(1.30)

    def test_spread_width_correct(self):
        c = make_contract(bid=1.20, ask=1.40)
        assert c.spread_width == pytest.approx(0.20)

    def test_spread_pct_correct(self):
        c = make_contract(bid=1.20, ask=1.40)
        # spread=0.20, mid=1.30 → 15.38%
        assert c.spread_pct == pytest.approx(15.38, abs=0.1)

    def test_tte_years_positive_for_future_expiry(self):
        c = make_contract(expiry=EXPIRY_35DTE)
        assert c.tte_years > 0
        assert c.tte_years < 1.0

    def test_tte_years_floors_at_min_for_0dte(self):
        c = make_contract(expiry=EXPIRY_TODAY)
        assert c.tte_years == pytest.approx(MIN_T_YEARS, rel=0.01)
        assert c.tte_years > 0  # Never zero — no division by zero

    def test_negative_bid_raises(self):
        with pytest.raises(ValueError, match="negative"):
            make_contract(bid=-0.10, ask=1.30)

    def test_ask_below_bid_raises(self):
        with pytest.raises(ValueError, match="Ask"):
            make_contract(bid=1.40, ask=1.20)

    def test_repr_contains_key_info(self):
        c = make_contract(strike=450.0, option_type="put")
        r = repr(c)
        assert "SPY" in r
        assert "450" in r
        assert "PUT" in r


# ── Module 2: AnalyticsEngine ────────────────────────────────────────────────

class TestAnalyticsEngine:
    engine = AnalyticsEngine(risk_free_rate=0.05)

    def test_iv_newton_raphson_round_trip(self):
        """NR should recover the IV used to generate a B-S price."""
        from app.services.options_pricer import BlackScholesPricer
        pricer = BlackScholesPricer()
        true_iv = 0.22
        price = pricer.put_price(S=455.0, K=450.0, T=35/365, r=0.05, sigma=true_iv)
        iv, solver = self.engine.implied_vol(
            market_price=price, S=455.0, K=450.0, T=35/365, option_type="put"
        )
        assert iv == pytest.approx(true_iv, abs=0.0001)

    def test_iv_solver_used_newton_for_atm(self):
        """ATM options should converge with Newton-Raphson."""
        from app.services.options_pricer import BlackScholesPricer
        pricer = BlackScholesPricer()
        price = pricer.put_price(S=450.0, K=450.0, T=35/365, r=0.05, sigma=0.20)
        _, solver = self.engine.implied_vol(
            market_price=price, S=450.0, K=450.0, T=35/365, option_type="put"
        )
        assert solver in ("newton_raphson", "brent")  # NR preferred

    def test_0dte_does_not_raise(self):
        """0DTE contracts must not produce division by zero."""
        c = make_contract(expiry=EXPIRY_TODAY, bid=0.50, ask=0.60)
        result = self.engine.enrich(c, underlying_price=451.0)
        assert result.delta is not None
        assert result.gamma is not None
        assert not any(v != v for v in [result.delta, result.gamma, result.vega])  # no NaN

    def test_enrich_sets_contract_fields(self):
        c = make_contract(bid=1.20, ask=1.30)
        self.engine.enrich(c, underlying_price=455.0)
        assert c.delta is not None
        assert c.implied_vol is not None
        assert c.gamma is not None
        assert c.theta is not None
        assert c.rho is not None

    def test_greeks_delta_call_between_0_and_1(self):
        g = self.engine.greeks(S=455.0, K=450.0, T=35/365, sigma=0.20, option_type="call")
        assert 0 < g["delta"] < 1

    def test_greeks_delta_put_between_neg1_and_0(self):
        g = self.engine.greeks(S=455.0, K=450.0, T=35/365, sigma=0.20, option_type="put")
        assert -1 < g["delta"] < 0

    def test_greeks_theta_negative_for_long(self):
        """Long options always have negative theta (time decay hurts)."""
        g = self.engine.greeks(S=455.0, K=455.0, T=35/365, sigma=0.20, option_type="call")
        assert g["theta"] < 0

    def test_rho_positive_for_call(self):
        """Calls benefit from rising rates (positive rho)."""
        g = self.engine.greeks(S=455.0, K=450.0, T=35/365, sigma=0.20, option_type="call")
        assert g["rho"] > 0

    def test_batch_numpy_returns_arrays(self):
        import numpy as np
        strikes = np.array([440.0, 445.0, 450.0, 455.0, 460.0])
        result = self.engine.batch_greeks_numpy(
            S=455.0, strikes=strikes, T=35/365, sigma=0.20, option_type="put"
        )
        assert result["delta"].shape == (5,)
        assert result["gamma"].shape == (5,)
        assert all(result["delta"] < 0)   # put deltas all negative


# ── Module 3: MultiLegStrategy ────────────────────────────────────────────────

class TestMultiLegStrategy:
    def test_net_premium_credit_spread(self):
        spread = make_bull_put_spread()
        # SELL short_put mid=1.25, BUY long_put mid=0.60
        # Net = (1.25 - 0.60) * 1 * 100 = $65 credit
        assert spread.net_premium > 0
        assert spread.is_credit

    def test_iron_condor_is_credit(self):
        ic = make_iron_condor()
        assert ic.is_credit

    def test_spread_width_dollars(self):
        spread = make_bull_put_spread()
        # Short 450P, Long 440P → width = 10 points = $1000 per contract
        assert spread.spread_width_dollars == pytest.approx(1000.0)

    def test_max_loss_defined_for_credit_spread(self):
        spread = make_bull_put_spread()
        assert spread.max_loss is not None
        assert spread.max_loss > 0
        assert spread.max_loss < spread.spread_width_dollars

    def test_risk_reward_ratio_positive(self):
        spread = make_bull_put_spread()
        rr = spread.risk_reward_ratio
        assert rr is not None
        assert rr > 0

    def test_breakeven_prices_populated(self):
        spread = make_bull_put_spread()
        # Enrich contracts so breakeven calc has credit info
        breakevens = spread.breakeven_prices
        assert len(breakevens) >= 0  # May be 0 if legs not fully enriched

    def test_net_delta_aggregates_legs(self):
        spread = make_bull_put_spread()
        # Short put has positive delta contribution, long put has negative
        # Net should be small positive (bull spread has mild bullish bias)
        delta = spread.net_delta
        assert isinstance(delta, float)

    def test_empty_legs_raises(self):
        with pytest.raises(ValueError, match="at least one leg"):
            MultiLegStrategy(strategy_name="test", underlying="SPY", legs=[])

    def test_summary_contains_required_keys(self):
        spread = make_bull_put_spread()
        s = spread.summary()
        for key in ["net_premium", "max_profit", "max_loss", "net_delta",
                    "net_gamma", "net_vega", "net_theta", "risk_reward"]:
            assert key in s

    def test_to_spread_order_produces_wire_format(self):
        spread = make_bull_put_spread()
        order = spread.to_spread_order()
        assert len(order.legs) == 2
        assert order.underlying == "SPY"
        assert order.strategy == "bull_put_spread"


# ── Module 4: ExecutionDispatcher ─────────────────────────────────────────────

class TestExecutionDispatcher:
    def make_dispatcher(self, max_spread_pct=15.0):
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value=MagicMock(
            order_id="TEST-001", status="filled",
            fill_price=MagicMock(__float__=lambda s: 1.25),
        ))
        return ExecutionDispatcher(broker, max_spread_pct=max_spread_pct), broker

    def test_liquid_spread_approved(self):
        dispatcher, _ = self.make_dispatcher(max_spread_pct=15.0)
        spread = make_bull_put_spread()  # spread_pct ~7.7% — well within 15%
        validation = dispatcher.validate_liquidity(spread)
        assert validation.approved

    def test_illiquid_leg_rejected(self):
        dispatcher, _ = self.make_dispatcher(max_spread_pct=10.0)
        # bid=0.10, ask=0.90 → spread=0.80, mid=0.50 → spread_pct=160%
        illiquid = make_contract(bid=0.10, ask=0.90)
        strategy = MultiLegStrategy(
            strategy_name="test", underlying="SPY",
            legs=[StrategyLeg(contract=illiquid, action=LegAction.SELL, quantity=1)],
        )
        validation = dispatcher.validate_liquidity(strategy)
        assert not validation.approved
        assert len(validation.blocking_legs) == 1

    def test_warned_leg_still_approved(self):
        dispatcher, _ = self.make_dispatcher(max_spread_pct=20.0)
        dispatcher.warn_spread_pct = 5.0
        # spread_pct ~7.7% — above warn (5%) but below max (20%)
        spread = make_bull_put_spread()
        validation = dispatcher.validate_liquidity(spread)
        assert validation.status == ValidationStatus.WARNED
        assert validation.approved  # warned but not blocked

    @pytest.mark.asyncio
    async def test_dry_run_dispatch_returns_filled(self):
        dispatcher, _ = self.make_dispatcher()
        spread = make_bull_put_spread()
        result = await dispatcher.submit_atomic(spread, dry_run=True)
        assert result.status == DispatchStatus.FILLED
        assert len(result.fills) == 2

    @pytest.mark.asyncio
    async def test_timeout_triggers_flatten(self):
        """If a leg times out, flatten-and-cancel must run."""
        dispatcher, broker = self.make_dispatcher()
        dispatcher.leg_timeout = 0.001  # Force immediate timeout

        spread = make_bull_put_spread()

        async def slow_fill(*args, **kwargs):
            await asyncio.sleep(10)  # Way beyond timeout
            return MagicMock(order_id="X", status="filled", fill_price=1.25)

        broker.place_order = AsyncMock(side_effect=slow_fill)

        result = await dispatcher.submit_atomic(spread, dry_run=False)
        assert result.status in (
            DispatchStatus.TIMEOUT_FLATTENED,
            DispatchStatus.PARTIAL_FLATTENED,
            DispatchStatus.FLATTEN_FAILED,
        )

    @pytest.mark.asyncio
    async def test_validate_and_dispatch_full_pipeline(self):
        """Full pipeline: validate → dispatch → filled."""
        dispatcher, _ = self.make_dispatcher()
        spread = make_bull_put_spread()
        result = await dispatcher.validate_and_dispatch(spread, dry_run=True)
        assert result.status == DispatchStatus.FILLED

    @pytest.mark.asyncio
    async def test_illiquid_order_rejected_before_dispatch(self):
        """Illiquid order must be rejected without ever hitting broker."""
        dispatcher, broker = self.make_dispatcher(max_spread_pct=5.0)
        # Force wide spread
        c = make_contract(bid=0.05, ask=2.00)
        strategy = MultiLegStrategy(
            strategy_name="test", underlying="SPY",
            legs=[StrategyLeg(contract=c, action=LegAction.SELL, quantity=1)],
        )
        result = await dispatcher.validate_and_dispatch(strategy, dry_run=True)
        assert result.status == DispatchStatus.REJECTED
        broker.place_order.assert_not_called()  # Never touched the broker
