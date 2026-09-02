"""
GET /api/options/signals crashed with `TypeError: 'numpy.bool_' object is not
iterable` inside FastAPI's jsonable_encoder — unlike numpy.float64 (a real
subclass of Python's float, which serializes fine), numpy.bool_ is NOT a
subclass of Python's bool, so a numpy-typed comparison result silently
poisons any response it ends up in. ScoreResult.approved/.uncertain are
computed via a `>=`/`<` comparison against effective_threshold, which can be
a numpy-typed value depending on how it was sourced — SignalScorer.score()
must always return native bool regardless of the comparison operands' types.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.signal_scorer import SignalFeatures, SignalScorer


def _features(**overrides) -> SignalFeatures:
    defaults = dict(
        iv_rank=50.0, iv_percentile=50.0, vix_level=18.0,
        spy_rsi_14=55.0, spy_adx_14=25.0, spy_trend_direction=1.0,
        days_to_expiry=35.0, short_strike_delta=0.20,
        spread_width=5.0, credit_to_width_ratio=0.30,
        earnings_days_away=30.0, spy_realized_vol_20d=0.15,
        iv_minus_rv=0.03,
    )
    defaults.update(overrides)
    return SignalFeatures(**defaults)


def _heuristic_scorer(ror_threshold) -> SignalScorer:
    """A SignalScorer forced onto the no-model heuristic path (bypasses
    __init__'s model-file loading), with a caller-supplied threshold type —
    lets us simulate a numpy-typed threshold without needing a real model."""
    scorer = SignalScorer.__new__(SignalScorer)
    scorer.model = None
    scorer.model_version = "untrained"
    scorer.model_type = "classifier"
    scorer._ror_threshold = ror_threshold
    scorer._explainer = None
    return scorer


@pytest.mark.parametrize("threshold_type", [float, np.float64, np.float32])
def test_approved_and_uncertain_are_always_native_bool(threshold_type):
    scorer = _heuristic_scorer(ror_threshold=0.12)
    result = scorer.score(_features(), threshold=threshold_type(0.3))

    assert type(result.approved) is bool
    assert type(result.uncertain) is bool
    # np.bool_ is falsy-compatible with bool but is NOT an instance of it —
    # this is the exact distinction the production bug hinged on.
    assert not isinstance(result.approved, np.bool_)
    assert not isinstance(result.uncertain, np.bool_)


def test_approved_true_case_is_native_bool_not_just_truthy():
    scorer = _heuristic_scorer(ror_threshold=0.12)
    # Threshold set low enough that a well-formed heuristic score clears it.
    result = scorer.score(_features(), threshold=np.float64(0.01))

    assert result.approved is True
    assert type(result.approved) is bool


def test_explain_evidence_dict_carries_native_bool():
    """The exact payload shape that flows into the options-signals response —
    explain()'s output is what actually got embedded in _recent_options_signals."""
    scorer = _heuristic_scorer(ror_threshold=0.12)
    result = scorer.score(_features(), threshold=np.float64(0.3))
    evidence = scorer.explain(result)

    assert type(evidence["approved"]) is bool
    assert type(evidence["uncertain"]) is bool
