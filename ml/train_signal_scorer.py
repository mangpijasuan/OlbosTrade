"""
XGBoost signal scorer training script.
Run after completing backtests to generate labeled training data.
Saves trained model to ml/model_registry/signal_scorer_v1.pkl

Usage:
    python ml/train_signal_scorer.py
"""

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from ml.features import FEATURE_NAMES, build_feature_matrix


def train(backtest_results_path: str = "backtest_results.json") -> None:
    """
    Train the XGBoost signal scorer.

    Args:
        backtest_results_path: Path to JSON file containing backtest trade records
    """
    try:
        from xgboost import XGBClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.metrics import roc_auc_score, classification_report
        import yfinance as yf
    except ImportError as e:
        print(f"Missing dependency: {e}. Run: pip install xgboost scikit-learn yfinance")
        sys.exit(1)

    print("Loading backtest results...")
    results_path = Path(backtest_results_path)
    if not results_path.exists():
        print(f"No backtest results at {results_path}. Run backtests first.")
        sys.exit(1)

    with open(results_path) as f:
        trades = json.load(f)

    print(f"Loaded {len(trades)} trades")

    # Fetch historical data for feature computation
    print("Fetching SPY history for feature engineering...")
    spy = yf.Ticker("SPY").history(period="5y", auto_adjust=True)
    spy.index = pd.to_datetime(spy.index).tz_localize(None)

    vix = yf.Ticker("^VIX").history(period="5y", auto_adjust=True)
    vix.index = pd.to_datetime(vix.index).tz_localize(None)
    vix_series = vix["Close"]

    # Use realized vol as IV proxy for training
    log_ret = np.log(spy["Close"] / spy["Close"].shift(1))
    iv_proxy = log_ret.rolling(20).std() * np.sqrt(252)

    print("Building feature matrix...")
    df = build_feature_matrix(
        ohlcv=spy,
        iv_history=iv_proxy,
        vix_history=vix_series,
        trades=trades,
    )

    if df.empty or "label" not in df.columns:
        print("No valid training samples found")
        sys.exit(1)

    X = df[FEATURE_NAMES].values
    y = df["label"].values

    pos_rate = y.mean()
    print(f"Training samples: {len(X)}, profitable rate: {pos_rate:.1%}")

    if len(X) < 50:
        print("Warning: fewer than 50 samples. Model may not generalize well.")

    # Train XGBoost
    scale_pos_weight = (1 - pos_rate) / pos_rate if pos_rate > 0 else 1.0
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
    )

    # Cross-validate
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")
    print(f"Cross-validated ROC AUC: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # Final fit on all data
    model.fit(X, y)
    train_pred = model.predict_proba(X)[:, 1]
    train_auc = roc_auc_score(y, train_pred)
    print(f"Training ROC AUC: {train_auc:.3f}")
    print(classification_report(y, (train_pred >= 0.65).astype(int),
                                  target_names=["loss", "profit"]))

    # Feature importance
    print("\nFeature Importances:")
    importances = model.feature_importances_
    for name, imp in sorted(zip(FEATURE_NAMES, importances), key=lambda x: -x[1]):
        print(f"  {name:<30} {imp:.4f}")

    # Save
    output_path = Path("ml/model_registry/signal_scorer_v1.pkl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump({
            "model": model,
            "version": "v1",
            "feature_names": FEATURE_NAMES,
            "train_auc": train_auc,
            "cv_auc_mean": float(cv_scores.mean()),
            "cv_auc_std": float(cv_scores.std()),
            "n_samples": len(X),
        }, f)

    print(f"\nModel saved to {output_path}")
    print("Re-load the SignalScorer in the backend to use the new model.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "backtest_results.json"
    train(path)
