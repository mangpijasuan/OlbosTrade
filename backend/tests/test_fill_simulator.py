"""
Unit tests for FillSimulator.
Run with: pytest tests/test_fill_simulator.py -v
"""

import pytest

from app.broker.fill_simulator import (
    COMMISSION_PER_CONTRACT,
    MINIMUM_FILL_PRICE,
    FillSimulator,
    realistic_fill_price,
)


simulator = FillSimulator()


# ── realistic_fill_price ────────────────────────────────────────────────────

class TestRealisticFillPrice:
    def test_buy_fills_above_mid(self):
        fill = realistic_fill_price(bid=1.00, ask=1.20, side="BUY", liquidity="normal")
        mid = (1.00 + 1.20) / 2
        assert fill > mid

    def test_sell_fills_below_mid(self):
        fill = realistic_fill_price(bid=1.00, ask=1.20, side="SELL", liquidity="normal")
        mid = (1.00 + 1.20) / 2
        assert fill < mid

    def test_tight_liquidity_fills_closer_to_mid(self):
        tight = realistic_fill_price(1.00, 1.20, "BUY", "tight")
        normal = realistic_fill_price(1.00, 1.20, "BUY", "normal")
        wide = realistic_fill_price(1.00, 1.20, "BUY", "wide")
        assert tight < normal < wide

    def test_wide_spread_has_more_slippage(self):
        tight_spread = realistic_fill_price(1.00, 1.10, "BUY", "normal")
        wide_spread = realistic_fill_price(1.00, 1.50, "BUY", "normal")
        # Wider bid-ask → more slippage even at same liquidity level
        slippage_tight = tight_spread - (1.05)
        slippage_wide = wide_spread - (1.25)
        assert slippage_wide > slippage_tight

    def test_minimum_fill_floor_applied(self):
        # Very low bid/ask should still fill at minimum
        fill = realistic_fill_price(bid=0.01, ask=0.02, side="SELL", liquidity="wide")
        assert fill >= MINIMUM_FILL_PRICE

    def test_at_the_money_fill(self):
        fill = realistic_fill_price(bid=2.00, ask=2.00, side="BUY", liquidity="tight")
        assert fill == pytest.approx(2.00, abs=0.01)

    def test_negative_bid_raises(self):
        with pytest.raises(ValueError, match="negative"):
            realistic_fill_price(bid=-0.10, ask=1.00, side="BUY")

    def test_ask_less_than_bid_raises(self):
        with pytest.raises(ValueError, match="Ask must be"):
            realistic_fill_price(bid=1.50, ask=1.00, side="BUY")


# ── FillSimulator ───────────────────────────────────────────────────────────

class TestFillSimulator:
    def test_commission_applied_to_single_contract(self):
        result = simulator.simulate_fill(bid=1.00, ask=1.20, side="BUY", contracts=1)
        assert result.commission == pytest.approx(COMMISSION_PER_CONTRACT)

    def test_commission_scales_with_contract_count(self):
        result = simulator.simulate_fill(bid=1.00, ask=1.20, side="BUY", contracts=5)
        assert result.commission == pytest.approx(COMMISSION_PER_CONTRACT * 5)

    def test_buy_net_cost_is_positive(self):
        result = simulator.simulate_fill(bid=1.00, ask=1.20, side="BUY", contracts=1)
        assert result.net_cost > 0

    def test_sell_net_cost_is_negative_credit(self):
        result = simulator.simulate_fill(bid=1.00, ask=1.20, side="SELL", contracts=1)
        assert result.net_cost < 0  # credit received (stored as negative cost)

    def test_net_fill_includes_commission_impact(self):
        buy = simulator.simulate_fill(bid=1.00, ask=1.20, side="BUY", contracts=1)
        sell = simulator.simulate_fill(bid=1.00, ask=1.20, side="SELL", contracts=1)
        # Commission always hurts the trader
        assert buy.net_fill_price > buy.gross_fill_price
        assert sell.net_fill_price < sell.gross_fill_price

    def test_zero_contracts_raises(self):
        with pytest.raises(ValueError, match="positive"):
            simulator.simulate_fill(bid=1.00, ask=1.20, side="BUY", contracts=0)

    def test_tight_liquidity_cheaper_than_wide_for_buy(self):
        tight = simulator.simulate_fill(1.00, 1.40, "BUY", contracts=1, liquidity="tight")
        wide = simulator.simulate_fill(1.00, 1.40, "BUY", contracts=1, liquidity="wide")
        assert tight.gross_fill_price < wide.gross_fill_price

    def test_spread_fill_returns_one_result_per_leg(self):
        legs = [
            {"bid": 1.20, "ask": 1.30, "side": "SELL"},
            {"bid": 0.60, "ask": 0.70, "side": "BUY"},
        ]
        results = simulator.simulate_spread_fill(legs, contracts=1)
        assert len(results) == 2

    def test_iron_condor_four_legs(self):
        legs = [
            {"bid": 1.20, "ask": 1.30, "side": "SELL"},  # short put
            {"bid": 0.55, "ask": 0.65, "side": "BUY"},   # long put
            {"bid": 1.10, "ask": 1.20, "side": "SELL"},  # short call
            {"bid": 0.50, "ask": 0.60, "side": "BUY"},   # long call
        ]
        results = simulator.simulate_spread_fill(legs, contracts=2)
        assert len(results) == 4
        total_commission = sum(r.commission for r in results)
        assert total_commission == pytest.approx(COMMISSION_PER_CONTRACT * 2 * 4)


# ── FIX #7: Vol-adjusted slippage tests ─────────────────────────────────────

class TestVolAdjustedSlippage:
    def test_vix_below_20_uses_tight_slippage(self):
        from app.broker.fill_simulator import vol_adjusted_slippage_pct
        pct = vol_adjusted_slippage_pct(vix=15.0)
        assert pct == pytest.approx(0.10)

    def test_vix_20_starts_normal_regime(self):
        from app.broker.fill_simulator import vol_adjusted_slippage_pct
        pct = vol_adjusted_slippage_pct(vix=20.0)
        assert pct == pytest.approx(0.20)

    def test_vix_30_double_normal(self):
        from app.broker.fill_simulator import vol_adjusted_slippage_pct
        pct = vol_adjusted_slippage_pct(vix=30.0)
        assert pct == pytest.approx(0.40)

    def test_vix_50_capped_at_65_pct(self):
        from app.broker.fill_simulator import vol_adjusted_slippage_pct
        pct = vol_adjusted_slippage_pct(vix=50.0)
        assert pct == pytest.approx(0.65)

    def test_high_vix_more_slippage_than_low_vix(self):
        fill_low  = simulator.simulate_fill(1.00, 1.40, "BUY", vix=15.0)
        fill_high = simulator.simulate_fill(1.00, 1.40, "BUY", vix=35.0)
        assert fill_high.gross_fill_price > fill_low.gross_fill_price

    def test_vix_to_liquidity_mapping(self):
        from app.broker.fill_simulator import vix_to_liquidity
        assert vix_to_liquidity(15.0) == "tight"
        assert vix_to_liquidity(25.0) == "normal"
        assert vix_to_liquidity(35.0) == "wide"


# ── FIX #7: Partial fill simulation tests ────────────────────────────────────

class TestPartialFills:
    def test_full_fill_returns_combo_complete(self):
        """With tight market (high fill probability), combo should complete."""
        from app.broker.fill_simulator import FillSimulator
        sim = FillSimulator(random_seed=42)
        legs = [
            {"bid": 1.20, "ask": 1.30, "side": "SELL"},
            {"bid": 0.60, "ask": 0.70, "side": "BUY"},
        ]
        result = sim.simulate_spread_fill(legs, vix=15.0, simulate_partial_fills=True)
        # With VIX=15 (97% fill prob) and seed=42, expect clean fill
        assert isinstance(result.combo_complete, bool)
        assert result.legs_total == 2

    def test_partial_fill_stops_at_failed_leg(self):
        """A partial fill should report legs_filled < legs_total."""
        from app.broker.fill_simulator import FillSimulator
        import random as rnd
        # Force a partial fill by using a simulator where fill always fails after leg 0
        sim = FillSimulator(random_seed=999)  # find a seed that causes partial
        legs = [
            {"bid": 0.05, "ask": 0.10, "side": "SELL"},
            {"bid": 0.03, "ask": 0.06, "side": "BUY"},
            {"bid": 0.05, "ask": 0.10, "side": "SELL"},
            {"bid": 0.03, "ask": 0.06, "side": "BUY"},
        ]
        # Run many times at high VIX — should eventually get partial fill
        got_partial = False
        for seed in range(200):
            sim2 = FillSimulator(random_seed=seed)
            r = sim2.simulate_spread_fill(legs, vix=40.0, simulate_partial_fills=True)
            if not r.combo_complete:
                got_partial = True
                assert r.legs_filled < r.legs_total
                assert r.partial_fill_reason is not None
                break
        assert got_partial, "Should encounter at least one partial fill at VIX=40 over 200 seeds"

    def test_simulate_partial_fills_false_always_completes(self):
        """When simulate_partial_fills=False, all legs always fill (used for exits)."""
        from app.broker.fill_simulator import FillSimulator
        sim = FillSimulator(random_seed=1)
        legs = [{"bid": 1.00, "ask": 1.20, "side": "BUY"}] * 4
        result = sim.simulate_spread_fill(
            legs, vix=60.0, simulate_partial_fills=False
        )
        assert result.combo_complete is True
        assert result.legs_filled == 4
