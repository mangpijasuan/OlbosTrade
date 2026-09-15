"""
Hysteresis on regime changes.

The interesting tests here are not "does it delay a change" — that is one
line. They are the three ways a guard like this turns into a NEW bug:

  1. delaying risk-off (CRISIS must never wait),
  2. going stale while it holds (the 2h staleness gate would slam everything
     to UNKNOWN, which is worse than the churn being fixed),
  3. freezing the features/confidence the rest of the system reads.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.regime_classifier import REGIME_CONFIG, RegimeState, RegimeType
from app.services.regime_stabilizer import RegimeStabilizer


def state(regime: RegimeType, *, confidence: float = 0.8, at=None) -> RegimeState:
    cfg = REGIME_CONFIG[regime]
    return RegimeState(
        regime=regime,
        description=cfg["description"],
        confidence=confidence,
        strategies_allowed=cfg["strategies_allowed"],
        equity_strategies_allowed=cfg.get("equity_strategies_allowed", []),
        size_multiplier=cfg["size_multiplier"],
        equity_size_multiplier=cfg.get("equity_size_multiplier", 0.5),
        options_size_multiplier=cfg.get("options_size_multiplier", cfg["size_multiplier"]),
        signal_threshold=cfg["signal_threshold_override"],
        iron_condor_allowed=cfg["iron_condor_allowed"],
        credit_spread_allowed=cfg["credit_spread_allowed"],
        classified_at=at or datetime.now(timezone.utc),
        features_used=None,
        reasoning=[],
    )


NORMAL = RegimeType.NORMAL_MEAN_REVERT
HIGHVOL = RegimeType.HIGH_VOL_TRENDING
LOWVOL = RegimeType.LOW_VOL_TRENDING
CRISIS = RegimeType.CRISIS


class TestHoldsUntilConfirmed:
    def test_first_reading_is_adopted_immediately(self):
        st = RegimeStabilizer(required=3)
        out = st.observe(state(NORMAL))
        assert out.state.regime is NORMAL
        assert not out.held

    def test_a_single_divergent_reading_does_not_change_the_regime(self):
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        out = st.observe(state(HIGHVOL))
        assert out.state.regime is NORMAL, "one reading flipped the regime"
        assert out.held
        assert out.pending is HIGHVOL and out.pending_count == 1

    def test_change_is_adopted_on_the_required_reading_and_not_before(self):
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        assert st.observe(state(HIGHVOL)).state.regime is NORMAL   # 1/3
        assert st.observe(state(HIGHVOL)).state.regime is NORMAL   # 2/3
        out = st.observe(state(HIGHVOL))                           # 3/3
        assert out.state.regime is HIGHVOL
        assert not out.held

    def test_a_disagreeing_reading_resets_the_count(self):
        """The whipsaw case: near a threshold the reading alternates."""
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        st.observe(state(HIGHVOL))          # 1/3
        st.observe(state(NORMAL))           # back — count must clear
        out = st.observe(state(HIGHVOL))    # starts again at 1/3
        assert out.pending_count == 1
        assert out.state.regime is NORMAL

    def test_alternating_readings_never_adopt_anything(self):
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        for _ in range(20):
            st.observe(state(HIGHVOL))
            out = st.observe(state(NORMAL))
        assert out.state.regime is NORMAL

    def test_a_third_regime_replaces_the_pending_candidate(self):
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        st.observe(state(HIGHVOL))          # pending HIGHVOL 1/3
        out = st.observe(state(LOWVOL))     # different candidate
        assert out.pending is LOWVOL and out.pending_count == 1

    def test_required_one_reproduces_the_unguarded_behaviour(self):
        """The documented escape hatch must actually disable the guard."""
        st = RegimeStabilizer(required=1)
        st.observe(state(NORMAL))
        out = st.observe(state(HIGHVOL))
        assert out.state.regime is HIGHVOL
        assert not out.held

    @pytest.mark.parametrize("bad, expected", [(0, 1), (-5, 1)])
    def test_nonsense_required_values_clamp_to_no_guard(self, bad, expected):
        assert RegimeStabilizer(required=bad).required == expected


class TestRiskOffIsNeverDelayed:
    """The way this guard could cost real money."""

    def test_crisis_is_adopted_on_the_very_first_reading(self):
        st = RegimeStabilizer(required=5)
        st.observe(state(NORMAL))
        out = st.observe(state(CRISIS))
        assert out.state.regime is CRISIS, "CRISIS was delayed by the guard"
        assert not out.held
        assert out.state.size_multiplier == 0.0

    def test_crisis_wins_even_with_another_candidate_pending(self):
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        st.observe(state(HIGHVOL))          # pending
        out = st.observe(state(CRISIS))
        assert out.state.regime is CRISIS

    def test_leaving_crisis_still_requires_confirmation(self):
        """One calm reading must not put capital back to work."""
        st = RegimeStabilizer(required=3)
        st.observe(state(CRISIS))
        assert st.observe(state(NORMAL)).state.regime is CRISIS
        assert st.observe(state(NORMAL)).state.regime is CRISIS
        assert st.observe(state(NORMAL)).state.regime is NORMAL


class TestHoldingDoesNotGoStale:
    """
    main._ensure_fresh_regime() resets the regime to UNKNOWN when
    classified_at is older than MAX_REGIME_AGE_SECONDS (2h). A hold can last
    longer than that, so a held state MUST carry a fresh timestamp — otherwise
    the guard trips the staleness gate and slams the desk to UNKNOWN, which is
    strictly worse than the churn it exists to remove.
    """

    def test_a_held_state_carries_a_refreshed_timestamp(self):
        st = RegimeStabilizer(required=10)
        old = datetime.now(timezone.utc) - timedelta(hours=6)
        st.observe(state(NORMAL, at=old))
        out = st.observe(state(HIGHVOL))
        age = (datetime.now(timezone.utc) - out.state.classified_at).total_seconds()
        assert age < 5, f"held state is {age:.0f}s stale — the staleness gate would fire"

    def test_a_long_hold_never_accumulates_age(self):
        st = RegimeStabilizer(required=100)
        st.observe(state(NORMAL))
        for _ in range(50):
            out = st.observe(state(HIGHVOL))
        age = (datetime.now(timezone.utc) - out.state.classified_at).total_seconds()
        assert age < 5

    def test_a_hold_records_why_in_the_reasoning(self):
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        out = st.observe(state(HIGHVOL))
        assert any("stabilizer" in r for r in out.state.reasoning)
        assert any(HIGHVOL.value in r for r in out.state.reasoning)

    def test_reasoning_does_not_grow_without_bound_on_the_source_state(self):
        """Held states are rebuilt from the previous held state; make sure a
        long hold does not accumulate one note per reading forever."""
        st = RegimeStabilizer(required=1000)
        st.observe(state(NORMAL))
        for _ in range(100):
            out = st.observe(state(HIGHVOL))
        assert len(out.state.reasoning) < 200


class TestUnchangedReadingsStayFresh:
    def test_an_unchanged_regime_adopts_the_new_confidence_and_features(self):
        """The decision is sticky; the data behind it must not be."""
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL, confidence=0.60))
        out = st.observe(state(NORMAL, confidence=0.95))
        assert out.state.confidence == 0.95, "stabilizer froze a stale confidence"

    def test_a_later_hold_carries_the_latest_confidence_not_the_first(self):
        """
        Asserting on the return value alone is not enough: the returned object
        is the fresh one whether or not the stabilizer stored it. What proves
        the refresh actually happened is a HOLD afterwards, because a held
        state is rebuilt from what was stored.
        """
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL, confidence=0.60))
        st.observe(state(NORMAL, confidence=0.95))
        out = st.observe(state(HIGHVOL))          # held -> rebuilt from storage
        assert out.held
        assert out.state.confidence == 0.95, (
            "the held state carries confidence from an older reading — "
            "the stabilizer is storing a stale RegimeState"
        )

    def test_an_unchanged_regime_clears_a_pending_candidate(self):
        st = RegimeStabilizer(required=3)
        st.observe(state(NORMAL))
        st.observe(state(HIGHVOL))
        out = st.observe(state(NORMAL))
        assert out.pending is None and out.pending_count == 0
