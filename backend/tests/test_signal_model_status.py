"""
Which scorer is actually running must be visible, and a bad artifact must not
take scoring down.

Background: a trained model sat in backend/ml/model_registry/ while the Docker
build context was ./backend with that path gitignored, so no model ever reached
the image. Production ran heuristic scoring for months and said so only in a
startup log line. Separately, the model that *would* have shipped records
r2=-0.173 and directional_accuracy=0.507 — it loads perfectly and has no skill,
which is the case `usable` exists to catch.

Run with: pytest tests/test_signal_model_status.py -v
"""

from __future__ import annotations

import pickle
from pathlib import Path
from unittest.mock import patch

from app.services.signal_scorer import SignalScorer


class XGBRegressor:  # noqa: N801 — name is load-bearing
    """Picklable stand-in for the real estimator.

    A MagicMock cannot be pickled, and the class *name* matters: _load_model
    falls back to `"Regressor" in type(model).__name__` for artifacts saved
    before model_type was recorded.
    """

    def predict(self, X):  # pragma: no cover — never called in these tests
        return [0.0]


def _scorer_with(saved, tmp_path: Path, *, corrupt: bool = False) -> SignalScorer:
    p = tmp_path / "model.pkl"
    if corrupt:
        p.write_bytes(b"this is not a pickle")
    else:
        p.write_bytes(pickle.dumps(saved))
    with patch("app.services.signal_scorer.settings") as s:
        s.model_path = str(p)
        return SignalScorer()


def _good_model():
    # SHAP's TreeExplainer will reject this and _load_model's own try/except
    # logs and continues — the documented "scores will lack explanations" path.
    # No patching needed; that fallback is real behaviour worth exercising.
    return XGBRegressor()


# ── a bad artifact must fall back, not explode ───────────────────────────────

def test_corrupt_pickle_falls_back_to_heuristics(tmp_path):
    """Unguarded, this raised inside __init__ and took down every caller that
    constructed a scorer. The heuristic path already exists and is correct."""
    sc = _scorer_with(None, tmp_path, corrupt=True)

    assert sc.model is None
    assert sc.status()["scoring_mode"] == "heuristic"
    assert sc.status()["path_exists"] is True, (
        "the file is present — it is the contents that are unusable, and the "
        "status must not conflate the two"
    )


def test_pickle_without_a_model_key_falls_back(tmp_path):
    sc = _scorer_with({"version": "v9", "metrics": {}}, tmp_path)
    assert sc.model is None
    assert sc.status()["loaded"] is False


def test_missing_file_reports_heuristic_not_error(tmp_path):
    with patch("app.services.signal_scorer.settings") as s:
        s.model_path = str(tmp_path / "nope.pkl")
        sc = SignalScorer()
    st = sc.status()
    assert st["loaded"] is False and st["path_exists"] is False
    assert st["scoring_mode"] == "heuristic"


# ── loading is not the same as being any good ────────────────────────────────

def test_negative_r2_is_reported_unusable(tmp_path):
    """The real artifact's numbers. It loads cleanly and predicts worse than
    the mean — 'loaded' must not be allowed to imply 'working'."""
    sc = _scorer_with({
        "model": _good_model(),
        "version": "v1-20260814",
        "model_type": "regressor",
        "metrics": {"r2": -0.173, "directional_accuracy": 0.5068, "n_val": 442},
    }, tmp_path)

    st = sc.status()
    assert st["loaded"] is True
    assert st["usable"] is False
    assert "negative" in st["usable_reason"]
    # Reported verbatim, not rounded away or omitted for looking bad.
    assert st["validation_metrics"]["r2"] == -0.173


def test_coin_flip_accuracy_is_reported_unusable(tmp_path):
    sc = _scorer_with({
        "model": _good_model(),
        "metrics": {"r2": 0.02, "directional_accuracy": 0.51},
    }, tmp_path)
    st = sc.status()
    assert st["usable"] is False and "coin flip" in st["usable_reason"]


def test_a_genuinely_good_model_is_reported_usable(tmp_path):
    sc = _scorer_with({
        "model": _good_model(),
        "metrics": {"r2": 0.31, "directional_accuracy": 0.62},
    }, tmp_path)
    st = sc.status()
    assert st["usable"] is True and st["scoring_mode"] == "model"


def test_status_never_claims_usable_without_a_model(tmp_path):
    """Guard against the inverse error: an empty metrics dict must not fall
    through to 'acceptable bounds' when nothing is loaded."""
    with patch("app.services.signal_scorer.settings") as s:
        s.model_path = str(tmp_path / "absent.pkl")
        sc = SignalScorer()
    assert sc.status()["usable"] is False
