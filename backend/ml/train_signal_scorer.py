"""
Train the AI signal scorer (XGBoost regressor predicting return-on-risk).

Labeled data comes from the walk-forward backtester, not the live trades
table — the account has only a handful of real closed trades so far, nowhere
near enough to train on directly. The backtester generates hundreds of
labeled entries per strategy across historical SPY data instead; live trades
become the natural retraining/validation set once there's enough real history.

Usage (from backend/, with the venv active):
    python3 -m ml.train_signal_scorer
    python3 -m ml.train_signal_scorer --start 2019-01-01 --end 2026-01-01
    python3 -m ml.train_signal_scorer --strategies bull_put_spread iron_condor

Writes ml/model_registry/signal_scorer_v1.pkl in the exact format
app.services.signal_scorer.SignalScorer._load_model() expects.
"""

from __future__ import annotations

import argparse
import asyncio
import pickle
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Make `app` and `ml` importable regardless of the invocation cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

STRATEGIES = ["bull_put_spread", "bear_call_spread", "iron_condor", "bull_call_debit_spread"]

# A high override so the (currently untrained) scorer gate never suppresses
# entries during data collection — we want the strategies' own entry rules
# to decide what counts as a candidate trade, unbiased by the model we're
# about to train on this same data.
COLLECTION_SCORE_OVERRIDE = 0.99

MIN_TRAINING_ROWS = 60  # below this, XGBoost is just memorizing noise


async def collect_trades(strategies: list[str], start: str, end: str, starting_capital: float):
    from app.broker.broker_factory import get_broker
    from app.services.backtester import Backtester, BacktestTrade
    from app.services.data_fetcher import DataFetcher

    broker = get_broker()
    fetcher = DataFetcher(broker)
    bt = Backtester(fetcher)

    all_trades: list[BacktestTrade] = []
    for strat in strategies:
        print(f"[collect] {strat}: {start} → {end} ...")
        result = await bt.run(
            strategy_name=strat, start_date=start, end_date=end,
            starting_capital=starting_capital,
            signal_score_override=COLLECTION_SCORE_OVERRIDE,
        )
        # Force-closed end-of-backtest trades carry an artificial pnl=0 label
        # — not a real outcome, exclude them.
        closed = [t for t in result.trades if t.exit_reason != "backtest_end"]
        print(f"         {len(closed)} closed trades, "
              f"return={result.metrics.total_return_pct*100:.1f}%, "
              f"Sharpe={result.metrics.sharpe_ratio:.2f}" if result.metrics else
              f"         {len(closed)} closed trades")
        all_trades.extend(closed)
    return all_trades


def build_dataset(trades: list) -> pd.DataFrame:
    from ml.features import FEATURE_NAMES, features_from_trade, ror_label

    rows = []
    for t in trades:
        row = features_from_trade(t)
        row["ror"] = ror_label(t)
        row["entry_date"] = t.entry_date
        row["strategy"] = t.strategy
        rows.append(row)
    df = pd.DataFrame(rows, columns=FEATURE_NAMES + ["ror", "entry_date", "strategy"])
    return df.sort_values("entry_date").reset_index(drop=True)


def walk_forward_split(df: pd.DataFrame, val_frac: float = 0.2):
    split_idx = int(len(df) * (1 - val_frac))
    return df.iloc[:split_idx], df.iloc[split_idx:]


def train(train_df: pd.DataFrame, feature_names: list[str]):
    from xgboost import XGBRegressor

    model = XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        random_state=42,
    )
    model.fit(train_df[feature_names], train_df["ror"])
    return model


def evaluate(model, val_df: pd.DataFrame, feature_names: list[str]) -> dict:
    from sklearn.metrics import mean_absolute_error, r2_score

    preds = model.predict(val_df[feature_names])
    actual = val_df["ror"].to_numpy()
    directional_hits = np.sum(np.sign(preds) == np.sign(actual))
    return {
        "mae": float(mean_absolute_error(actual, preds)),
        "r2": float(r2_score(actual, preds)),
        "directional_accuracy": float(directional_hits / len(actual)) if len(actual) else 0.0,
        "n_val": len(val_df),
    }


def save_model(model, feature_names: list[str], output_path: Path, ror_threshold: float,
                cutoff_date: date, metrics: dict, n_train: int, n_val: int):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "version": f"v1-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        "model_type": "regressor",
        "ror_threshold": ror_threshold,
        "feature_names": feature_names,
        "date_range": {"to": cutoff_date.isoformat(), "staleness_days": 90},
        "metrics": {**metrics, "n_train": n_train},
    }
    with open(output_path, "wb") as f:
        pickle.dump(payload, f)


async def main() -> None:
    from app.core.config import settings
    from app.services.signal_scorer import DEFAULT_ROR_THRESHOLD, FEATURE_NAMES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategies", nargs="+", default=STRATEGIES, choices=STRATEGIES)
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--capital", type=float, default=25000.0)
    parser.add_argument("--val-frac", type=float, default=0.2)
    args = parser.parse_args()

    trades = await collect_trades(args.strategies, args.start, args.end, args.capital)
    print(f"\n[collect] total closed trades across {len(args.strategies)} strategies: {len(trades)}")

    if len(trades) < MIN_TRAINING_ROWS:
        print(f"\n❌ Only {len(trades)} labeled trades — need at least {MIN_TRAINING_ROWS} "
              "for XGBoost to learn anything beyond noise. Widen --start/--end or add strategies.")
        return

    df = build_dataset(trades)
    train_df, val_df = walk_forward_split(df, args.val_frac)
    print(f"[split] train={len(train_df)} rows ({train_df['entry_date'].min()} → {train_df['entry_date'].max()}), "
          f"val={len(val_df)} rows ({val_df['entry_date'].min()} → {val_df['entry_date'].max()})")

    if len(val_df) < 10:
        print("\n❌ Validation split too small to trust — collect more data (wider date range).")
        return

    model = train(train_df, FEATURE_NAMES)
    metrics = evaluate(model, val_df, FEATURE_NAMES)

    print("\n[validate] walk-forward holdout metrics:")
    print(f"           MAE (RoR):            {metrics['mae']:.4f}")
    print(f"           R²:                   {metrics['r2']:.4f}")
    print(f"           Directional accuracy: {metrics['directional_accuracy']*100:.1f}% "
          f"(n={metrics['n_val']})")

    importances = sorted(
        zip(FEATURE_NAMES, model.feature_importances_), key=lambda x: -x[1]
    )
    print("\n[importance] top features:")
    for name, imp in importances[:8]:
        print(f"           {name:<24} {imp:.3f}")

    if metrics["directional_accuracy"] < 0.55:
        print(
            "\n⚠  Directional accuracy is barely better than a coin flip. "
            "Saving anyway, but this model is not ready to gate real trades — "
            "widen the date range, add more strategies, or revisit feature "
            "engineering (vix_term_slope is a constant right now; see ml/features.py)."
        )

    output_path = Path(settings.model_path)
    if not output_path.is_absolute():
        output_path = Path(__file__).resolve().parents[1] / output_path
    cutoff = pd.to_datetime(df["entry_date"].max()).date()
    save_model(model, FEATURE_NAMES, output_path, DEFAULT_ROR_THRESHOLD, cutoff,
               metrics, len(train_df), len(val_df))
    print(f"\n✅ Saved: {output_path}")
    print("   Restart the backend (or let the next scan cycle pick it up) to load the new model.")


if __name__ == "__main__":
    asyncio.run(main())
