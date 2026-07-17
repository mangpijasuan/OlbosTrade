"""
Regression coverage for the regime staleness gate (_ensure_fresh_regime).

ARCHITECTURE_AUDIT.md finding #6: _reclassify_regime() logs and returns on
data failure, silently keeping whatever classification is already in
_current_regime with no age check -- a regime from hours ago could gate
strategy selection indefinitely. Separately, an unclassified regime (None)
was fail-open for equities (main.py's equity branch treats None as "not
blocked") but fail-closed for options (_run_options_scan returns immediately
on None) -- two policies for the same "we don't know the regime" state.

_ensure_fresh_regime() unifies both onto UNKNOWN's own fail-open,
reduced-size policy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.main as m
from app.services.regime_classifier import RegimeState, RegimeType


def _regime_state(regime: RegimeType, classified_at: datetime) -> RegimeState:
    return RegimeState(
        regime=regime,
        description="test",
        confidence=0.8,
        strategies_allowed=["bull_put_spread"],
        equity_strategies_allowed=["momentum_long"],
        size_multiplier=1.0,
        equity_size_multiplier=1.0,
        options_size_multiplier=1.0,
        signal_threshold=0.65,
        iron_condor_allowed=False,
        credit_spread_allowed=True,
        classified_at=classified_at,
    )


def test_none_regime_becomes_unknown():
    m._current_regime = None
    m._ensure_fresh_regime()
    assert m._current_regime is not None
    assert m._current_regime.regime == RegimeType.UNKNOWN
    # UNKNOWN must be fail-open for BOTH equity and options at reduced size --
    # this is the exact asymmetry the audit flagged.
    assert m._current_regime.equity_allowed is True
    assert m._current_regime.options_allowed is True


def test_fresh_regime_is_left_untouched():
    now = datetime.now(timezone.utc)
    fresh = _regime_state(RegimeType.NORMAL_MEAN_REVERT, now - timedelta(minutes=10))
    m._current_regime = fresh
    m._ensure_fresh_regime()
    assert m._current_regime is fresh
    assert m._current_regime.regime == RegimeType.NORMAL_MEAN_REVERT


def test_stale_regime_resets_to_unknown():
    now = datetime.now(timezone.utc)
    stale = _regime_state(
        RegimeType.HIGH_VOL_TRENDING,
        now - timedelta(seconds=m.MAX_REGIME_AGE_SECONDS + 60),
    )
    m._current_regime = stale
    m._ensure_fresh_regime()
    assert m._current_regime is not stale
    assert m._current_regime.regime == RegimeType.UNKNOWN
    assert m._current_regime.equity_allowed is True
    assert m._current_regime.options_allowed is True


def test_regime_exactly_at_threshold_is_not_yet_stale():
    now = datetime.now(timezone.utc)
    borderline = _regime_state(
        RegimeType.NORMAL_MEAN_REVERT,
        now - timedelta(seconds=m.MAX_REGIME_AGE_SECONDS - 5),
    )
    m._current_regime = borderline
    m._ensure_fresh_regime()
    assert m._current_regime is borderline
