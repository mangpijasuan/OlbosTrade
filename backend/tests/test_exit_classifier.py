"""
Tests for exit_classifier.classify_broker_exit.

The bias under test is that the classifier fails toward UNKNOWN. Most of what
follows asserts that it declines to label rather than that it labels — a
false `stop_hit` would poison the exact measurement this exists to enable.
"""
from types import SimpleNamespace

import pytest

from app.services.exit_classifier import (
    STOP_HIT,
    TARGET_HIT,
    UNKNOWN,
    classify_broker_exit,
)


def _long(entry=100.0, stop=95.0, target=110.0):
    return SimpleNamespace(
        spread_type="equity_long",
        credit_received=entry,
        long_strike=stop,
        short_strike=entry,
        target_price=target,
    )


def _short(entry=100.0, stop=105.0, target=90.0):
    return SimpleNamespace(
        spread_type="equity_short",
        credit_received=entry,
        long_strike=stop,
        short_strike=entry,
        target_price=target,
    )


# ── The two things it should name ──────────────────────────────────────────

def test_long_filled_at_stop_is_stop_hit():
    assert classify_broker_exit(_long(), 95.0) == STOP_HIT


def test_long_gapped_through_stop_is_still_stop_hit():
    # Gaps fill worse than the stop; that is the common case, not an edge one.
    assert classify_broker_exit(_long(), 91.20) == STOP_HIT


def test_long_filled_at_target_is_target_hit():
    assert classify_broker_exit(_long(), 110.0) == TARGET_HIT


def test_short_filled_at_stop_is_stop_hit():
    assert classify_broker_exit(_short(), 105.0) == STOP_HIT


def test_short_filled_at_target_is_target_hit():
    assert classify_broker_exit(_short(), 90.0) == TARGET_HIT


def test_short_sides_are_not_the_long_rules_reversed_by_accident():
    # A short exiting BELOW entry is a win, not a stop-out. Long logic applied
    # to a short would call this a stop.
    assert classify_broker_exit(_short(), 92.0) != STOP_HIT


# ── Everything it must refuse to name ──────────────────────────────────────

def test_exit_between_the_levels_is_unknown():
    # Closed at the broker somewhere in the middle — a manual close, an
    # external flatten, anything. Not classifiable.
    assert classify_broker_exit(_long(), 102.0) == UNKNOWN


def test_placeholder_stop_never_classifies_as_stop_hit():
    # Reconciler-adopted rows write avg_cost into entry and stop alike. Read
    # literally, nearly every exit is "at the stop". This is the trap that
    # equity_stop_distance() exists to reject.
    trade = _long(entry=100.0, stop=100.0, target=None)
    assert classify_broker_exit(trade, 99.5) == UNKNOWN


def test_stop_on_the_wrong_side_for_direction_is_unknown():
    # A long whose "stop" sits above entry is a broken row, not a stop.
    trade = _long(entry=100.0, stop=108.0, target=None)
    assert classify_broker_exit(trade, 108.0) == UNKNOWN


def test_target_on_the_wrong_side_for_direction_is_ignored():
    trade = _long(entry=100.0, stop=95.0, target=90.0)
    assert classify_broker_exit(trade, 90.0) == STOP_HIT


def test_missing_target_still_allows_stop_classification():
    trade = _long(target=None)
    assert classify_broker_exit(trade, 95.0) == STOP_HIT
    assert classify_broker_exit(trade, 110.0) == UNKNOWN


def test_options_trade_is_never_classified():
    trade = SimpleNamespace(
        spread_type="put", credit_received=2.0,
        long_strike=95.0, short_strike=100.0, target_price=1.0,
    )
    assert classify_broker_exit(trade, 1.0) == UNKNOWN


@pytest.mark.parametrize("bad", [None, 0, -5.0, "abc"])
def test_unusable_exit_price_is_unknown(bad):
    assert classify_broker_exit(_long(), bad) == UNKNOWN


def test_missing_entry_price_is_unknown():
    trade = _long()
    trade.credit_received = None
    assert classify_broker_exit(trade, 95.0) == UNKNOWN


def test_target_below_the_stop_is_ignored_not_treated_as_a_target():
    trade = _long(entry=100.0, stop=95.0, target=94.0)
    assert classify_broker_exit(trade, 94.0) == STOP_HIT


def test_levels_close_enough_to_both_match_refuse_to_pick_a_side():
    # Reachable, not hypothetical: a stop 0.2% under entry clears the
    # placeholder check, and a target 0.1% over entry leaves a fill at entry
    # inside both tolerances. The row cannot say which leg filled.
    trade = _long(entry=100.0, stop=99.8, target=100.1)
    assert classify_broker_exit(trade, 100.0) == UNKNOWN


def test_never_raises_on_a_garbage_row():
    assert classify_broker_exit(object(), 100.0) == UNKNOWN
    assert classify_broker_exit(None, 100.0) == UNKNOWN


def test_tolerance_does_not_swallow_a_clearly_better_fill():
    # 2% above the stop is not a stop fill.
    assert classify_broker_exit(_long(), 96.9) == UNKNOWN
