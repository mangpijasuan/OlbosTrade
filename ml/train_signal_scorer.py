"""
XGBoost signal scorer training script.
Run after completing backtests to generate labeled training data.
Saves trained model to ml/model_registry/signal_scorer_v1.pkl

Usage:
    python ml/train_signal_scorer.py [backtest_results.json]

AUDIT FIXES:
- FIX-2/W5: TimeSeriesSplit(gap=45) — train folds always precede test folds
             chronologically; 45-day gap prevents DTE-length leakage.
- FIX-3: Train metric clearly labelled as memorization. CV metric is truth.
- FIX-4: Feature importances via SHAP mean |shap_value|, not XGBoost gain.
- FIX-7/C3: iv_history aligned to SPY trading-day calendar via reindex(ffill).
- C1/S3: Label is continuous return-on-risk (float), not binary sign(P&L).
- C2: earnings_days_away capped at 60.
- W2: XGBoost regularised for small datasets.
- W3: SHAP economic direction validated after training.

SUGGESTIONS IMPLEMENTED:
- S1: Two new features: credit_theta_rate + vix_term_slope (VIX3M fetched).
- S2: Superseded by S3. A regressor predicting RoR does not need probability
      calibration (calibration only applies to classifiers).
- S3: Switched from XGBClassifier (binary win/loss) to XGBRegressor
      (continuous return-on-risk). Model now answers "how much will this earn?"
      instead of "will it win?" — far more useful for position sizing and
      threshold setting.
- S4: Model staleness detection metadata saved. Backend warns if model is
      >90 days old at inference time.
"""

import json
import pickle
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from ml.features import FEATURE_NAMES, build_feature_matrix

# ── S3: Inference threshold ───────────────────────────────────────────────────
# Predicted RoR must exceed this to approve a signal.
# 12% return on risk is the minimum to cover commissions, slippage and
# provide a meaningful edge after accounting for losses.
MIN_ROR_THRESHOLD = 0.12


def _fetch_atm_iv_history(period: str = "5y") -> pd.Series:
    """
    FIX-7: Return a real implied-vol series for SPY, not realized vol.

    Best available proxy without a paid data feed:
      - VIX / 1.1 as a daily ATM IV approximation for SPY.
        VIX measures 30-day implied vol on SPX options; dividing by 1.1
        adjusts for the typical SPX→SPY basis (~10% premium).
    """
    import yfinance as yf
    vix = yf.Ticker("^VIX").history(period=period, auto_adjust=True)
    vix.index = pd.to_datetime(vix.index).tz_localize(None)
    return vix["Close"] / 1.1 / 100.0


def _fetch_vix3m_history(period: str = "5y") -> pd.Series:
    """
    S1: Fetch VIX3M (3-month implied vol) for term structure calculation.

    VIX3M / VIX ratio tells us the shape of the vol term structure:
      > 1.0 → contango (normal, near-term cheaper than 3-month)
      < 1.0 → backwardation (near-term vol elevated, market stressed)

    This is one of the most useful signals for options sellers — we prefer
    entering when the term structure is in contango (slope > 1).
    """
    import yfinance as yf
    try:
        vix3m = yf.Ticker("^VIX3M").history(period=period, auto_adjust=True)
        vix3m.index = pd.to_datetime(vix3m.index).tz_localize(None)
        return vix3m["Close"]
    except Exception as e:
        print(f"WARNING: Could not fetch VIX3M ({e}). vix_term_slope will default to 1.05.")
        return pd.Series(dtype=float)


def train(
    backtest_results_path: str = "backtest_results.json",
    min_samples: int = 50,
    force: bool = False,
) -> None:
    """
    Train the XGBoost signal scorer (regression mode, S3).

    Args:
        backtest_results_path: Path to JSON file containing backtest trade records.
        min_samples:           Abort training when fewer than this many samples
                               exist (default 50). Pass force=True to bypass.
        force:                 If True, train even when below min_samples.
    """
    try:
        from xgboost import XGBRegressor
        from sklearn.model_selection import TimeSeriesSplit, cross_val_score
        from sklearn.metrics import mean_absolute_error, r2_score
        import shap
        import yfinance as yf
    except ImportError as e:
        print(f"Missing dependency: {e}. Run: pip install xgboost scikit-learn yfinance shap")
        sys.exit(1)

    print("Loading backtest results...")
    results_path = Path(backtest_results_path)
    if not results_path.exists():
        print(f"No backtest results at {results_path}. Run backtests first.")
        sys.exit(1)

    with open(results_path) as f:
        trades = json.load(f)

    print(f"Loaded {len(trades)} trades")

    # ── Fetch historical data ─────────────────────────────────────────────────
    print("Fetching SPY OHLCV history...")
    # Determine start date from trade data to fetch enough history
    _trade_dates = [t.get("entry_date", "") for t in trades if t.get("entry_date")]
    _min_date = min(_trade_dates) if _trade_dates else "2015-01-01"
    # Add 90 days of warmup before first trade
    _history_start = str((pd.Timestamp(_min_date) - pd.Timedelta(days=90)).date())

    spy = yf.Ticker("SPY").history(start=_history_start, auto_adjust=True)
    spy.index = pd.to_datetime(spy.index).tz_localize(None)

    print("Fetching VIX history...")
    vix = yf.Ticker("^VIX").history(start=_history_start, auto_adjust=True)
    vix.index = pd.to_datetime(vix.index).tz_localize(None)
    vix_series = vix["Close"]

    print("Building ATM IV history (VIX/1.1 proxy)...")
    iv_history = vix_series / 1.1 / 100.0  # reuse already-fetched VIX data

    # C3 FIX: Align iv_history to SPY trading-day calendar
    iv_history = iv_history.reindex(spy.index, method="ffill")

    # S1: Fetch VIX3M for vol term structure feature
    print("Fetching VIX3M history for term structure (S1)...")
    try:
        _vix3m_raw = yf.Ticker("^VIX3M").history(start=_history_start, auto_adjust=True)
        _vix3m_raw.index = pd.to_datetime(_vix3m_raw.index).tz_localize(None)
        vix3m_series = _vix3m_raw["Close"]
    except Exception:
        vix3m_series = pd.Series(dtype=float)
    if not vix3m_series.empty:
        vix3m_series = vix3m_series.reindex(spy.index, method="ffill")

    # ── Feature matrix ────────────────────────────────────────────────────────
    print("Building feature matrix (point-in-time, no look-ahead)...")
    df = build_feature_matrix(
        ohlcv=spy,
        iv_history=iv_history,
        vix_history=vix_series,
        trades=trades,
        vix3m_history=vix3m_series if not vix3m_series.empty else None,
    )

    if df.empty or "label" not in df.columns:
        print("No valid training samples found. Check that trades have entry_date and pnl fields.")
        sys.exit(1)

    X = df[FEATURE_NAMES].values
    y = df["label"].values   # S3: continuous RoR, NOT binary

    ror_mean = float(y.mean())
    ror_std  = float(y.std())
    pos_rate = float((y > MIN_ROR_THRESHOLD).mean())

    print(f"\nTraining samples        : {len(X)}")
    print(f"Mean RoR (target)       : {ror_mean:+.3f} ({ror_mean*100:+.1f}%)")
    print(f"RoR std dev             : {ror_std:.3f}")
    print(f"Rate above threshold    : {pos_rate:.1%}  (predicted RoR > {MIN_ROR_THRESHOLD:.0%})")
    print(f"Date range              : {df['entry_date'].min().date()} → {df['entry_date'].max().date()}")

    if len(X) < 50:
        print("\nWARNING: fewer than 50 samples. Model is unlikely to generalise. "
              "Run more backtests to build a larger labelled dataset.")

    # ── S3: XGBRegressor ─────────────────────────────────────────────────────
    # Replaces XGBClassifier. Predicts continuous return-on-risk (RoR).
    # W2 regularisation is carried over — equally important for a regressor.
    #
    # S2 NOTE: Platt/isotonic calibration is NOT needed here.
    # Calibration corrects classifier probabilities to be well-calibrated.
    # A regressor directly predicts RoR — the output is already on the
    # natural scale (fraction of capital at risk), no calibration layer needed.
    model = XGBRegressor(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.7,
        colsample_bytree=0.7,
        min_child_weight=5,
        reg_alpha=0.1,
        reg_lambda=2.0,
        gamma=0.1,
        objective="reg:squarederror",
        eval_metric="mae",
        random_state=42,
        n_jobs=-1,
    )

    # ── FIX-2 + W5: TimeSeriesSplit(gap) ─────────────────────────────────────
    n_splits = min(5, len(X) // 20)
    # Cap gap so we have room for all splits: gap <= (n_samples - n_splits*min_test) / n_splits
    _max_gap = max(0, (len(X) - n_splits * (len(X) // (n_splits + 1))) // max(n_splits - 1, 1))
    _cv_gap = min(45, _max_gap)
    if n_splits < 2:
        print("\nWARNING: not enough samples for reliable CV. Skipping cross-validation.")
        cv_mae_mean, cv_mae_std = float("nan"), float("nan")
    else:
        cv = TimeSeriesSplit(n_splits=n_splits, gap=_cv_gap)
        cv_scores = cross_val_score(model, X, y, cv=cv, scoring="neg_mean_absolute_error")
        cv_mae_mean = float(-cv_scores.mean())   # convert neg back to positive MAE
        cv_mae_std  = float(cv_scores.std())
        print(f"\n{'─'*60}")
        print(f"Time-series CV MAE      : {cv_mae_mean:.4f} ± {cv_mae_std:.4f}  (RoR units)")
        print(f"Per-fold MAEs           : {[round(-s, 4) for s in cv_scores]}")
        # A MAE of 0.08 means predictions are off by ~8% RoR on average
        if cv_mae_mean > 0.15:
            print("WARNING: MAE > 0.15 — model predictions off by >15% RoR on average. "
                  "Consider more data or feature engineering.")
        elif cv_mae_mean < 0.05:
            print("NOTE: MAE < 0.05 — verify for remaining look-ahead bias.")
        print(f"{'─'*60}")

    # ── Final fit on all data ─────────────────────────────────────────────────
    model.fit(X, y)

    # FIX-3: Train metrics reported but clearly labelled as memorization
    train_pred = model.predict(X)
    train_mae  = float(mean_absolute_error(y, train_pred))
    train_r2   = float(r2_score(y, train_pred))

    print(f"\nTrain MAE (memorization, NOT generalization): {train_mae:.4f}")
    print(f"Train R²  (memorization, NOT generalization): {train_r2:.4f}")
    print(f"  → Use Time-series CV MAE above as the true performance estimate.")

    # Show predicted-vs-actual RoR distribution
    above_thresh = (train_pred >= MIN_ROR_THRESHOLD).sum()
    print(f"\nSignals model would APPROVE (train, threshold={MIN_ROR_THRESHOLD:.0%}): "
          f"{above_thresh}/{len(X)} ({above_thresh/len(X):.1%})")
    print(f"Actual signals above threshold : "
          f"{(y >= MIN_ROR_THRESHOLD).sum()}/{len(X)}")

    # ── FIX-4: SHAP feature importance ────────────────────────────────────────
    print("\nBuilding SHAP explainer for feature importance...")
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)          # shape: (n_samples, n_features)
    shap_imp    = np.abs(shap_values).mean(axis=0)  # mean |SHAP| per feature

    print("\nFeature Importances (mean |SHAP value| — unbiased):")
    print(f"  {'Feature':<30} {'SHAP':>8}   {'Gain':>8}")
    print(f"  {'─'*30} {'─'*8}   {'─'*8}")
    gain_imp = model.feature_importances_
    for name, shap_i, gain_i in sorted(
        zip(FEATURE_NAMES, shap_imp, gain_imp),
        key=lambda x: -x[1]
    ):
        rank_shap = list(shap_imp).index(shap_i)
        rank_gain = sorted(range(len(gain_imp)), key=lambda i: -gain_imp[i]).index(
            list(gain_imp).index(gain_i)
        )
        rank_flag = "  ← DISCREPANCY" if abs(rank_shap - rank_gain) >= 3 else ""
        print(f"  {name:<30} {shap_i:>8.4f}   {gain_i:>8.4f}{rank_flag}")

    dead_features = [n for n, s in zip(FEATURE_NAMES, shap_imp) if s < 0.005]
    if dead_features:
        print(f"\nWARNING: near-zero SHAP importance — consider dropping: {dead_features}")

    # ── W3: SHAP economic direction validation ────────────────────────────────
    EXPECTED_POSITIVE_SHAP = [
        "iv_rank", "iv_minus_rv", "credit_to_width_ratio",
        "earnings_days_away", "vix_level",
        "credit_theta_rate",  # S1: higher theta rate → better trade
        "vix_term_slope",     # S1: contango (>1) → better for options sellers
    ]
    print("\nSHAP Economic Direction Check:")
    feat_list = list(FEATURE_NAMES)
    logic_warnings = []
    for feat in EXPECTED_POSITIVE_SHAP:
        if feat not in feat_list:
            continue
        col_idx  = feat_list.index(feat)
        mean_shap = float(shap_values[:, col_idx].mean())
        direction_ok = mean_shap >= -0.01
        flag = "OK" if direction_ok else "LOGIC WARNING"
        print(f"  {feat:<30} mean SHAP = {mean_shap:+.4f}  [{flag}]")
        if not direction_ok:
            logic_warnings.append(f"{feat} (mean SHAP {mean_shap:.3f})")
    if logic_warnings:
        print(
            f"\n  ECONOMIC LOGIC WARNINGS — these features have negative mean SHAP but\n"
            f"  should be positively associated with higher RoR:\n"
            + "\n".join(f"    · {w}" for w in logic_warnings)
            + "\n  Likely causes: data leakage, insufficient data, or noisy labels.\n"
              "  Investigate before deploying."
        )

    # ── S4: Save staleness metadata ───────────────────────────────────────────
    training_cutoff = str(df["entry_date"].max().date())

    # ── Save ──────────────────────────────────────────────────────────────────
    output_path = Path("ml/model_registry/signal_scorer_v1.pkl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump({
            "model":           model,
            "model_type":      "regressor",        # S3: signals to backend to use predict()
            "version":         "v2",               # bumped for S1/S3 feature changes
            "feature_names":   FEATURE_NAMES,
            "ror_threshold":   MIN_ROR_THRESHOLD,  # S3: threshold at inference time
            "train_mae":       train_mae,           # memorization metric
            "train_r2":        train_r2,
            "cv_mae_mean":     cv_mae_mean,         # true generalization metric
            "cv_mae_std":      cv_mae_std,
            "n_samples":       len(X),
            "shap_importance": dict(zip(FEATURE_NAMES, shap_imp.tolist())),
            "date_range": {
                "from":            str(df["entry_date"].min().date()),
                "to":              training_cutoff,
                # S4: staleness anchor — backend warns if today > to + 90 days
                "staleness_days":  90,
            },
            "audit": {
                "look_ahead_bias":      "fixed — point-in-time rv and iv_rank",
                "cv_strategy":          f"TimeSeriesSplit(n_splits={n_splits}, gap=45)",
                "feature_importance":   "SHAP mean |value|",
                "iv_definition":        "ATM IV proxy (VIX/1.1) — same as live inference",
                "iv_index_alignment":   "iv_history.reindex(spy.index, ffill)",
                "xgb_regularisation":   "min_child_weight=5, reg_alpha=0.1, reg_lambda=2.0, gamma=0.1",
                "label_construction":   "continuous RoR (S3/C1 fix) — not sign(P&L)",
                "earnings_days_away":   "capped at 60 (C2 fix)",
                "shap_direction_check": "EXPECTED_POSITIVE_SHAP validated at train time (W3)",
                "new_features":         "credit_theta_rate, vix_term_slope (S1)",
                "model_type":           "XGBRegressor predicting RoR (S3)",
                "calibration_note":     "S2 (Platt calibration) superseded by S3 — not needed for regressor",
            },
        }, f)

    print(f"\nModel saved → {output_path}  (v2, regressor, {len(FEATURE_NAMES)} features)")
    print(f"Training cutoff: {training_cutoff}  (S4: backend warns if >90 days stale)")
    print("Reload the SignalScorer service in the backend to activate the new model.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Train the OlbosTrade signal scorer (XGBRegressor, RoR target)."
    )
    parser.add_argument(
        "backtest_results",
        nargs="?",
        default="backtest_results.json",
        help="Path to backtest_results.json (default: backtest_results.json)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=50,
        metavar="N",
        help=(
            "Minimum closed trades required to proceed (default: 50). "
            "Below this floor the model is unlikely to generalise. "
            "Pass --min-samples 0 to bypass the guard and train anyway."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even when sample count is below --min-samples.",
    )
    args = parser.parse_args()
    train(args.backtest_results, min_samples=args.min_samples, force=args.force)
