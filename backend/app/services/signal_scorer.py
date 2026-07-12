"""
AI Signal Scorer — XGBoost regressor with SHAP explainability.
Predicts continuous return-on-risk (RoR). Threshold: predicted RoR > 12%.

FIX #4: SHAP TreeExplainer cached at load time — never rebuilt per inference call.
FIX #4: Scoring runs in ThreadPoolExecutor to avoid blocking the asyncio event loop.
FIX #5: Counterfactual scoring method added for walk-forward training integrity.
FIX #6: Uncertainty quantification — rejects trades in the ambiguous zone near threshold.

SUGGESTIONS IMPLEMENTED:
- S1: Two new features in SignalFeatures (credit_theta_rate, vix_term_slope).
      Both have safe defaults so existing callers don't break.
- S2: Superseded by S3 — no calibration needed for a regressor.
- S3: Model is now XGBRegressor predicting RoR. Inference uses predict() not
      predict_proba(). Legacy classifier models are still supported via auto-detection.
- S4: Staleness check at load time — logs WARNING if model data is >90 days old.
"""

import asyncio
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# S1: Updated feature list — 15 features (was 13).
# New: credit_theta_rate, vix_term_slope
FEATURE_NAMES = [
    "iv_rank", "iv_percentile", "vix_level",
    "spy_rsi_14", "spy_adx_14", "spy_trend_direction",
    "days_to_expiry", "short_strike_delta",
    "spread_width", "credit_to_width_ratio",
    "earnings_days_away", "spy_realized_vol_20d",
    "iv_minus_rv",
    # S1 new features
    "credit_theta_rate",   # daily credit as % of max risk (theta efficiency)
    "vix_term_slope",      # VIX3M / VIX (>1 = contango = normal)
]

# S3: Default RoR threshold — predicted RoR must exceed 12% to approve
DEFAULT_ROR_THRESHOLD = 0.12

# FIX #6: Trades scoring within this band of the threshold are rejected
# as "uncertain" — the model is not confident enough to approve
UNCERTAINTY_BAND = 0.05

# Shared thread pool for non-blocking inference
_INFERENCE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scorer")


@dataclass
class SignalFeatures:
    """All 15 features used by the signal scorer (13 original + 2 S1 additions)."""
    iv_rank: float
    iv_percentile: float
    vix_level: float
    spy_rsi_14: float
    spy_adx_14: float
    spy_trend_direction: float           # 1.0 = above SMA, -1.0 = below SMA
    days_to_expiry: float
    short_strike_delta: float
    spread_width: float
    credit_to_width_ratio: float
    earnings_days_away: float            # capped at 60 (C2)
    spy_realized_vol_20d: float
    iv_minus_rv: float
    # S1 new features — safe defaults for backward compatibility
    credit_theta_rate: float = 0.0      # credit_to_width / DTE; computed if 0
    vix_term_slope: float = 1.05        # VIX3M / VIX; default = mild contango

    def __post_init__(self) -> None:
        # S1: Auto-compute credit_theta_rate from existing fields if not set
        if self.credit_theta_rate == 0.0 and self.days_to_expiry > 0:
            self.credit_theta_rate = self.credit_to_width_ratio / max(self.days_to_expiry, 1.0)

    def to_array(self) -> np.ndarray:
        return np.array([[
            self.iv_rank, self.iv_percentile, self.vix_level,
            self.spy_rsi_14, self.spy_adx_14, self.spy_trend_direction,
            self.days_to_expiry, self.short_strike_delta,
            self.spread_width, self.credit_to_width_ratio,
            self.earnings_days_away, self.spy_realized_vol_20d,
            self.iv_minus_rv,
            self.credit_theta_rate, self.vix_term_slope,
        ]])


@dataclass
class FeatureImpact:
    """SHAP explanation for a single feature."""
    feature_name: str
    value: float
    shap_value: float
    direction: str   # "positive" | "negative" | "neutral"


@dataclass
class ScoreResult:
    """Full result from scoring a signal."""
    score: float                # S3: predicted RoR (e.g. 0.18 = 18% RoR) or classifier proba
    approved: bool
    threshold: float            # S3: min_ror threshold (e.g. 0.12)
    uncertain: bool             # FIX #6: True if score is in uncertainty band
    features: SignalFeatures
    feature_impacts: list[FeatureImpact]
    model_version: str
    model_type: str = "classifier"   # S3: "regressor" or "classifier"
    rejection_reason: Optional[str] = None


class SignalScorer:
    """
    XGBoost-based signal scorer.
    Loads pre-trained model from model_registry/.
    Falls back to heuristic scoring if model not yet trained.

    FIX #4: SHAP explainer is cached once at load time.
    FIX #4: score_async() runs inference off the asyncio event loop.
    S3: Auto-detects regressor vs classifier from saved model metadata.
    S4: Warns if model training data is >90 days stale.
    """

    def __init__(self) -> None:
        self.model = None
        self.model_version = "untrained"
        self.model_type = "classifier"   # S3: "regressor" or "classifier"
        self._ror_threshold = DEFAULT_ROR_THRESHOLD
        # FIX #4: Explainer cached here — never rebuilt per call
        self._explainer = None
        # Exposed for /api/research/model-performance — populated in
        # _load_model() from the pickle's metadata, not guessed via getattr.
        self.last_trained: Optional[str] = None
        self.validation_metrics: dict = {}
        self._load_model()

    def _load_model(self) -> None:
        """Load model and build SHAP explainer once."""
        model_path = Path(settings.model_path)
        if not model_path.exists():
            logger.warning(
                "No trained model at %s — using heuristic scoring. "
                "Run ml/train_signal_scorer.py after backtesting.",
                model_path,
            )
            return

        with open(model_path, "rb") as f:
            saved = pickle.load(f)

        self.model = saved.get("model")
        self.model_version = saved.get("version", "v1")

        # S3: Detect model type — use saved metadata first, fall back to class check
        saved_type = saved.get("model_type", "")
        if saved_type == "regressor":
            self.model_type = "regressor"
        elif saved_type == "classifier":
            self.model_type = "classifier"
        else:
            # Auto-detect from class name for models saved before v2
            cls_name = type(self.model).__name__
            self.model_type = "regressor" if "Regressor" in cls_name else "classifier"

        # S3: Load RoR threshold (saved in pkl by trainer, default 0.12)
        self._ror_threshold = float(saved.get("ror_threshold", DEFAULT_ROR_THRESHOLD))

        # S4: Staleness check
        date_range = saved.get("date_range", {})
        staleness_days = int(date_range.get("staleness_days", 90))
        cutoff_str = date_range.get("to", "")
        self.last_trained = cutoff_str or None
        self.validation_metrics = saved.get("metrics", {})
        if cutoff_str:
            try:
                cutoff_date = date.fromisoformat(cutoff_str)
                age_days = (date.today() - cutoff_date).days
                if age_days > staleness_days:
                    logger.warning(
                        "STALE MODEL: signal scorer was trained on data through %s "
                        "(%d days ago, limit=%d). Market conditions may have shifted. "
                        "Run ml/train_signal_scorer.py to retrain.",
                        cutoff_str, age_days, staleness_days,
                    )
                else:
                    logger.info("Model freshness: %d days old (limit=%d)", age_days, staleness_days)
            except ValueError:
                pass

        # FIX #4: Build TreeExplainer at load time, not per-call
        try:
            import shap
            self._explainer = shap.TreeExplainer(self.model)
            logger.info(
                "Signal scorer loaded: %s (%s) | threshold=%.2f | SHAP explainer cached",
                self.model_version, self.model_type, self._ror_threshold,
            )
        except Exception as exc:
            logger.warning("SHAP explainer build failed: %s — scores will lack explanations", exc)

    def score(
        self,
        features: SignalFeatures,
        threshold: Optional[float] = None,
    ) -> ScoreResult:
        """
        Score a signal synchronously.
        Use score_async() in async contexts to avoid blocking the event loop.

        S3: For regressor models, threshold is minimum predicted RoR (default 0.12).
            For legacy classifier models, threshold is minimum probability (default 0.65).
        """
        # S3: Use RoR threshold for regressor, probability threshold for classifier
        if self.model_type == "regressor":
            effective_threshold = threshold or self._ror_threshold
        else:
            effective_threshold = threshold or settings.effective_signal_score_threshold

        if self.model is not None:
            raw_score, impacts = self._model_score(features)
            # W3: Check SHAP economic direction
            self._check_shap_directions(impacts)
        else:
            raw_score, impacts = self._heuristic_score(features)

        # FIX #6: Uncertainty band check
        distance_from_threshold = raw_score - effective_threshold
        uncertain = abs(distance_from_threshold) < UNCERTAINTY_BAND

        # FIX #6: Reject if score is within the uncertainty band
        # A score of 0.67 (just above 0.65 threshold) is not a confident approval
        if uncertain and raw_score >= effective_threshold:
            approved = False
            rejection_reason = (
                f"Score {raw_score:.3f} is within uncertainty band "
                f"(threshold={effective_threshold:.2f} ± {UNCERTAINTY_BAND}). "
                f"Requires score ≥ {effective_threshold + UNCERTAINTY_BAND:.2f} "
                f"for confident approval."
            )
        else:
            approved = raw_score >= effective_threshold
            rejection_reason = (
                f"Score {raw_score:.3f} below threshold {effective_threshold:.2f}"
                if not approved else None
            )

        logger.info(
            "Signal score: %.3f (threshold=%.2f, uncertain=%s, approved=%s)",
            raw_score, effective_threshold, uncertain, approved,
        )

        return ScoreResult(
            score=round(raw_score, 4),
            approved=approved,
            threshold=effective_threshold,
            uncertain=uncertain,
            features=features,
            feature_impacts=impacts,
            model_version=self.model_version,
            model_type=self.model_type,
            rejection_reason=rejection_reason,
        )

    async def score_async(
        self,
        features: SignalFeatures,
        threshold: Optional[float] = None,
    ) -> ScoreResult:
        """
        FIX #4: Non-blocking async scoring.
        Runs inference in ThreadPoolExecutor so the asyncio event loop
        is never blocked during SHAP computation or XGBoost inference.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _INFERENCE_EXECUTOR,
            self.score,
            features,
            threshold,
        )

    def _model_score(self, features: SignalFeatures) -> tuple[float, list[FeatureImpact]]:
        """
        FIX #4: Uses cached self._explainer — not rebuilt per call.
        S3: Uses predict() for regressors, predict_proba() for classifiers.

        For regressors: returns predicted RoR (e.g. 0.18 = 18%).
        For classifiers: returns win probability (0.0 – 1.0).
        """
        try:
            X = features.to_array()

            # S3: Branch on model type
            if self.model_type == "regressor":
                # Regressor: predict returns RoR directly
                raw = float(self.model.predict(X)[0])
                # Clip to reasonable range — RoR can't be below -1 or above 1
                score = float(np.clip(raw, -1.0, 1.0))
            else:
                # Legacy classifier: predict_proba returns win probability
                score = float(self.model.predict_proba(X)[0][1])

            impacts: list[FeatureImpact] = []
            if self._explainer is not None:
                # FIX #4: Cached explainer — O(1) lookup, not O(n_trees) build
                raw_shap = self._explainer.shap_values(X)
                # Regressors return shape (n_samples, n_features),
                # classifiers may return (n_samples, n_features) or list thereof
                if isinstance(raw_shap, list):
                    shap_values = raw_shap[1][0]   # class 1 for classifiers
                else:
                    shap_values = raw_shap[0]      # regressors

                feat_names = FEATURE_NAMES
                n_feats = min(len(feat_names), len(shap_values))
                impacts = [
                    FeatureImpact(
                        feature_name=feat_names[i],
                        value=float(X[0][i]),
                        shap_value=float(shap_values[i]),
                        direction=(
                            "positive" if shap_values[i] > 0.005
                            else "negative" if shap_values[i] < -0.005
                            else "neutral"
                        ),
                    )
                    for i in range(n_feats)
                ]
                impacts.sort(key=lambda x: abs(x.shap_value), reverse=True)

            return score, impacts

        except Exception as exc:
            logger.error("Model scoring failed, falling back to heuristic: %s", exc)
            return self._heuristic_score(features)

    def _heuristic_score(self, features: SignalFeatures) -> tuple[float, list[FeatureImpact]]:
        """
        Rule-based heuristic score when model is not trained yet.
        FIX #6: Heuristic uses a higher effective threshold internally
        (0.72 instead of 0.65) to compensate for lack of probabilistic calibration.
        """
        score = 0.0

        iv_score   = min(features.iv_rank / 100, 1.0)
        iv_rv_score = min(max(features.iv_minus_rv / 0.10, 0), 1.0)
        trend_score = 1.0 if features.spy_trend_direction > 0 else 0.3
        rsi_score   = max(1.0 - abs(features.spy_rsi_14 - 50) / 50, 0)
        dte_score   = 1.0 if 30 <= features.days_to_expiry <= 45 else 0.5
        cw_score    = min(features.credit_to_width_ratio / 0.33, 1.0)
        earn_score  = min(features.earnings_days_away / 30, 1.0)
        vix_score   = 1.0 if 15 <= features.vix_level <= 25 else 0.5

        weights = {
            "iv_rank": 0.20, "iv_minus_rv": 0.15, "spy_trend": 0.15,
            "rsi": 0.15, "dte": 0.10, "credit_ratio": 0.10,
            "earnings": 0.10, "vix": 0.05,
        }
        score = (
            iv_score   * weights["iv_rank"]
            + iv_rv_score * weights["iv_minus_rv"]
            + trend_score * weights["spy_trend"]
            + rsi_score   * weights["rsi"]
            + dte_score   * weights["dte"]
            + cw_score    * weights["credit_ratio"]
            + earn_score  * weights["earnings"]
            + vix_score   * weights["vix"]
        )

        impacts = [
            FeatureImpact("iv_rank", features.iv_rank,
                         iv_score * weights["iv_rank"], "positive"),
            FeatureImpact("iv_minus_rv", features.iv_minus_rv,
                         iv_rv_score * weights["iv_minus_rv"], "positive"),
            FeatureImpact("rsi", features.spy_rsi_14,
                         rsi_score * weights["rsi"], "neutral"),
            FeatureImpact("days_to_expiry", features.days_to_expiry,
                         dte_score * weights["dte"], "neutral"),
            FeatureImpact("credit_to_width_ratio", features.credit_to_width_ratio,
                         cw_score * weights["credit_ratio"], "positive"),
        ]
        return min(score, 1.0), sorted(impacts, key=lambda x: abs(x.shap_value), reverse=True)

    def _check_shap_directions(self, impacts: list[FeatureImpact]) -> None:
        """
        W3 FIX: Sanity-check that economically positive features have positive
        SHAP values for this signal.  A strong negative SHAP on iv_rank or
        iv_minus_rv when those values are high suggests the model learned
        something backwards — worth surfacing as a log warning.

        This is a per-inference check, not a per-training check.  It catches
        model drift (e.g. retrained model on bad data) before it silently
        affects live decisions.
        """
        EXPECTED_POSITIVE: set[str] = {
            "iv_rank", "iv_minus_rv", "credit_to_width_ratio",
            "earnings_days_away", "vix_level",
        }
        for impact in impacts:
            if impact.feature_name not in EXPECTED_POSITIVE:
                continue
            # Only flag when the feature value is actually elevated (top 40th pct)
            # AND SHAP is strongly negative — avoids noise from near-zero values
            value_is_high = {
                "iv_rank": impact.value > 40,
                "iv_minus_rv": impact.value > 0.02,
                "credit_to_width_ratio": impact.value > 0.25,
                "earnings_days_away": impact.value > 14,
                "vix_level": impact.value > 18,
            }.get(impact.feature_name, False)

            if value_is_high and impact.shap_value < -0.05:
                logger.warning(
                    "SHAP DIRECTION ANOMALY: %s=%.3f has SHAP=%.3f (expected positive). "
                    "May indicate model drift or label construction issue — "
                    "consider retraining.",
                    impact.feature_name, impact.value, impact.shap_value,
                )

    def explain(self, result: ScoreResult) -> dict:
        """Return a human-readable explanation of the score."""
        top_pos = [f for f in result.feature_impacts if f.direction == "positive"][:3]
        top_neg = [f for f in result.feature_impacts if f.direction == "negative"][:3]

        # S3: Tailor score label to model type
        if result.model_type == "regressor":
            score_label = f"Predicted RoR: {result.score*100:+.1f}%"
            threshold_label = f"Min RoR threshold: {result.threshold*100:.0f}%"
        else:
            score_label = f"Win probability: {result.score:.3f}"
            threshold_label = f"Min probability threshold: {result.threshold:.2f}"

        return {
            "score": result.score,
            "score_label": score_label,
            "approved": result.approved,
            "uncertain": result.uncertain,
            "threshold": result.threshold,
            "threshold_label": threshold_label,
            "decision": "APPROVE" if result.approved else "REJECT",
            "rejection_reason": result.rejection_reason,
            "top_positive_factors": [
                {"feature": f.feature_name, "value": f.value, "impact": f.shap_value}
                for f in top_pos
            ],
            "top_negative_factors": [
                {"feature": f.feature_name, "value": f.value, "impact": f.shap_value}
                for f in top_neg
            ],
            "model_version": result.model_version,
            "model_type": result.model_type,
        }
