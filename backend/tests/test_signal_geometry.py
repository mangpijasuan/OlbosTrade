"""
The target/stop geometry, and the measurements that decide where it belongs.

Two things are under test here.

1. The multipliers come from settings rather than being welded into the
   engine, and the shipped defaults reproduce exactly the old hardcoded
   behaviour. That second half matters as much as the first: this change is
   meant to make the geometry *choosable*, not to quietly change it.

2. The R-based outcome maths, because `hit_rate` cannot answer "is the target
   in the right place". It excludes expiries, and expiry is not neutral —
   the stop sits nearer than the target, so slow winners expire while losers
   resolve, and the excluded pile is disproportionately made of signals that
   would have won.
"""

import pytest

from app.core.config import settings
from app.services.equity_signal_engine import (
    EquitySignalParams,
    compute_equity_trade_plan,
)
from app.services.signal_outcome_tracker import (
    compute_signal_outcome_stats,
    _counterfactual_expectancy,
    _mfe_r,
    _realised_r,
    _target_distance_r,
)


# ── Fixtures: 1R = 4.00 on the BUY, 2.00 on the SELL ─────────────────────

def buy(status, exit_price, mfe_pct, **kw):
    return dict(ticker="A", action="BUY", confidence=0.7, status=status,
                entry_price=100.0, stop_price=96.0, target_price=108.0,
                exit_price=exit_price, max_favorable_pct=mfe_pct,
                days_to_resolve=5, regime="calm", **kw)


def sell(status, exit_price, mfe_pct, **kw):
    return dict(ticker="B", action="SELL", confidence=0.7, status=status,
                entry_price=50.0, stop_price=52.0, target_price=46.0,
                exit_price=exit_price, max_favorable_pct=mfe_pct,
                days_to_resolve=5, regime="calm", **kw)


class TestGeometryIsConfigurable:
    def test_defaults_reproduce_the_previous_hardcoded_behaviour(self):
        """The point of the change is choosability, not a silent retune."""
        p = EquitySignalParams()
        assert (p.stop_atr_multiplier, p.target_atr_multiplier) == (2.0, 4.0)

    def test_the_plan_uses_the_configured_multipliers(self, monkeypatch):
        monkeypatch.setattr(settings, "equity_stop_atr_multiplier", 1.0)
        monkeypatch.setattr(settings, "equity_target_atr_multiplier", 2.5)

        # Constructed AFTER the patch: default_factory is what makes this
        # read settings at instantiation. A plain `= settings.x` default
        # would have bound once at import and ignored this entirely, which
        # is the failure mode this test exists to catch.
        plan = compute_equity_trade_plan(
            ind={"close": 100.0, "atr": 4.0}, action="BUY",
            portfolio_value=100_000, params=EquitySignalParams(),
        )
        assert plan["stop_price"] == pytest.approx(96.0)
        assert plan["target_price"] == pytest.approx(110.0)

    def test_sell_mirrors_the_multipliers(self):
        plan = compute_equity_trade_plan(
            ind={"close": 100.0, "atr": 2.0}, action="SELL",
            portfolio_value=100_000,
        )
        assert plan["stop_price"] == pytest.approx(104.0)
        assert plan["target_price"] == pytest.approx(92.0)


class TestRMaths:
    def test_realised_r_is_signed_by_direction(self):
        # A SELL that exits BELOW entry is a winner. Getting this backwards
        # would invert expectancy for every short signal while still looking
        # like a plausible number.
        assert _realised_r(buy("target_hit", 108.0, 0.08)) == pytest.approx(2.0)
        assert _realised_r(buy("stop_hit", 96.0, 0.02)) == pytest.approx(-1.0)
        assert _realised_r(sell("target_hit", 46.0, 0.08)) == pytest.approx(2.0)
        assert _realised_r(sell("stop_hit", 52.0, 0.01)) == pytest.approx(-1.0)

    def test_mfe_converts_percent_of_entry_into_r(self):
        # max_favorable_pct is a fraction of ENTRY, not of risk — it has to
        # go back through price before it can be divided by 1R.
        assert _mfe_r(buy("expired", 100.0, 0.06)) == pytest.approx(1.5)
        assert _mfe_r(sell("expired", 50.0, 0.06)) == pytest.approx(1.5)

    def test_target_distance_survives_a_change_of_multipliers(self):
        """4×ATR over a 2×ATR stop is 2.0R, and still 2.0R when both halve.

        This is the property that makes R the right unit to report in: the
        numbers stay comparable across exactly the retune this work exists
        to enable.
        """
        wide = dict(entry_price=100.0, stop_price=96.0, target_price=108.0)
        tight = dict(entry_price=100.0, stop_price=98.0, target_price=104.0)
        assert _target_distance_r(wide) == pytest.approx(2.0)
        assert _target_distance_r(tight) == pytest.approx(2.0)

    def test_rows_that_cannot_support_the_maths_return_none(self):
        # Callers pass outcome dicts of varying completeness; a missing field
        # must not take down the whole stats endpoint.
        assert _realised_r({"action": "BUY"}) is None
        assert _mfe_r({"entry_price": 100.0}) is None
        assert _target_distance_r({"entry_price": 100.0, "stop_price": 100.0}) is None


class TestExpectancyIsNotHitRate:
    def test_expired_signals_count_toward_expectancy(self):
        """The whole reason this metric exists.

        hit_rate drops expiries. Expectancy must not, or it inherits the same
        blind spot: an expiry that closed at +1.25R is real money, and a
        system whose winners mostly expire would look identical to one whose
        winners mostly lose.
        """
        rows = [
            buy("target_hit", 108.0, 0.08),
            buy("stop_hit", 96.0, 0.06),
            buy("expired", 105.0, 0.065),
            sell("stop_hit", 52.0, 0.02),
        ]
        stats = compute_signal_outcome_stats(rows)

        assert stats["hit_rate"] == pytest.approx(0.333, abs=0.001)
        assert stats["expectancy_r"] == pytest.approx(0.312, abs=0.001)
        assert stats["resolved_with_r"] == 4

        # Drop the expiry and the number moves — proof it was included.
        without = compute_signal_outcome_stats([r for r in rows if r["status"] != "expired"])
        assert without["expectancy_r"] != stats["expectancy_r"]

    def test_pending_signals_are_excluded(self):
        # A pending signal has no exit, so it has no realised R. Counting it
        # as 0 would drag expectancy toward zero purely with time.
        rows = [buy("target_hit", 108.0, 0.08),
                dict(buy("pending", None, None), exit_price=None)]
        stats = compute_signal_outcome_stats(rows)
        assert stats["resolved_with_r"] == 1
        assert stats["expectancy_r"] == pytest.approx(2.0)

    def test_hit_rate_can_be_breakeven_while_expectancy_is_positive(self):
        """The reason hit rate should stop being the headline number."""
        rows = [
            buy("target_hit", 108.0, 0.08),
            buy("stop_hit", 96.0, 0.06),
            buy("expired", 105.0, 0.065),
            sell("stop_hit", 52.0, 0.02),
        ]
        stats = compute_signal_outcome_stats(rows)
        assert stats["hit_rate"] < 0.34      # reads as breakeven-or-worse
        assert stats["expectancy_r"] > 0     # but the system made money


class TestTargetPlacementReadout:
    def test_mfe_buckets_show_where_signals_actually_topped_out(self):
        rows = [
            buy("stop_hit", 96.0, 0.006),    # 0.15R
            buy("stop_hit", 96.0, 0.024),    # 0.60R
            buy("expired", 104.0, 0.052),    # 1.30R
            buy("target_hit", 108.0, 0.084),  # 2.10R
        ]
        buckets = compute_signal_outcome_stats(rows)["by_mfe_bucket_r"]
        assert buckets["0.0-0.5R"] == 1
        assert buckets["0.5-1.0R"] == 1
        assert buckets["1.0-1.5R"] == 1
        assert buckets["2.0-3.0R"] == 1
        assert sum(buckets.values()) == 4     # nothing silently dropped

    def test_counterfactual_prefers_a_target_the_signals_can_reach(self):
        """The readout that answers the multiplier question.

        Four signals that all run past 1.5R but stall short of 2.0R. A target
        at 1.5R banks them; a target at 2.0R turns them into stops and
        expiries. The sweep has to make that visible, or it is decoration.
        """
        rows = [buy("expired", 100.0, 0.07) for _ in range(3)]  # MFE 1.75R, exit flat
        rows.append(buy("stop_hit", 96.0, 0.068))               # MFE 1.70R, then stopped

        at_1_5 = _counterfactual_expectancy(rows, 1.5)
        at_2_0 = _counterfactual_expectancy(rows, 2.0)
        assert at_1_5 == pytest.approx(1.5)
        assert at_2_0 < at_1_5

    def test_counterfactual_ignores_pending_rows(self):
        rows = [buy("target_hit", 108.0, 0.08),
                dict(buy("pending", None, None), exit_price=None)]
        assert _counterfactual_expectancy(rows, 2.0) == pytest.approx(2.0)

    def test_counterfactual_is_none_without_usable_rows(self):
        assert _counterfactual_expectancy([], 2.0) is None
