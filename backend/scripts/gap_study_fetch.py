"""
Phase 1 data pull for the overnight-gap study.

Pulls daily OHLCV through the app's own DataFetcher (broker first, yfinance
fallback — the same path every backtest in this repo uses) plus historical
earnings dates, and caches both to disk so the analysis can be re-run without
re-fetching.

No execution code. No order placement. Read-only.

Usage:
    python scripts/gap_study_fetch.py <out_dir> [start] [end]
"""

from __future__ import annotations

import asyncio
import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock

warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings           # noqa: E402
from app.services.data_fetcher import DataFetcher  # noqa: E402


async def fetch_prices(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """Daily OHLCV for every symbol, long-format.

    DataFetcher tries the broker first and falls back to yfinance on any
    exception. There is no broker connection in this context, so the MagicMock
    fails instantly and every symbol resolves through the documented yfinance
    fallback — the same arrangement the strategy-optimizer timing check uses.
    Keeping the real DataFetcher in the path (rather than calling yfinance
    directly) means this study reads prices exactly the way the rest of the
    system does, including its adjustment behaviour.
    """
    fetcher = DataFetcher(broker=MagicMock())
    frames: list[pd.DataFrame] = []

    for i, sym in enumerate(symbols, 1):
        try:
            df = await fetcher.fetch_ohlcv(sym, start, end)
            if df is None or df.empty:
                print(f"  [{i}/{len(symbols)}] {sym}: EMPTY", flush=True)
                continue
            df = df.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
            df["symbol"] = sym
            frames.append(df)
            print(f"  [{i}/{len(symbols)}] {sym}: {len(df)} rows", flush=True)
        except Exception as exc:
            print(f"  [{i}/{len(symbols)}] {sym}: FAILED {type(exc).__name__}: {exc}", flush=True)

    if not frames:
        raise SystemExit("no price data fetched")
    return pd.concat(frames, ignore_index=True)


def fetch_earnings(symbols: list[str]) -> pd.DataFrame:
    """Historical earnings announcement timestamps.

    Yahoo caps `limit` at 100, which reaches back ~25 years for a quarterly
    reporter — comfortably past this study's window. Symbols that return
    nothing are recorded as having no coverage rather than silently treated as
    'never had earnings', so the analysis can exclude them from the earnings
    segment instead of misclassifying their gaps as no-news.
    """
    rows: list[dict] = []
    covered: list[dict] = []

    for i, sym in enumerate(symbols, 1):
        try:
            ed = yf.Ticker(sym).get_earnings_dates(limit=100)
            if ed is None or len(ed) == 0:
                print(f"  [{i}/{len(symbols)}] {sym}: no earnings rows", flush=True)
                covered.append({"symbol": sym, "n": 0, "first": None, "last": None})
                continue
            idx = pd.to_datetime(ed.index, utc=True, errors="coerce").dropna()
            for ts in idx:
                rows.append({"symbol": sym, "earnings_ts": ts})
            covered.append({
                "symbol": sym, "n": len(idx),
                "first": idx.min().date().isoformat(),
                "last": idx.max().date().isoformat(),
            })
            print(f"  [{i}/{len(symbols)}] {sym}: {len(idx)} earnings dates "
                  f"({idx.min().date()} .. {idx.max().date()})", flush=True)
        except Exception as exc:
            print(f"  [{i}/{len(symbols)}] {sym}: FAILED {type(exc).__name__}: {exc}", flush=True)
            covered.append({"symbol": sym, "n": -1, "first": None, "last": None})

    return pd.DataFrame(rows), pd.DataFrame(covered)


async def main() -> None:
    out_dir = Path(sys.argv[1])
    start = sys.argv[2] if len(sys.argv) > 2 else "2015-01-01"
    end = sys.argv[3] if len(sys.argv) > 3 else pd.Timestamp.today().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = settings.get_equity_watchlist()
    print(f"Universe: {len(symbols)} symbols | window {start} .. {end}\n")

    print("── prices ──", flush=True)
    prices = await fetch_prices(symbols, start, end)
    prices.to_csv(out_dir / "prices.csv", index=False)
    print(f"\nprices: {len(prices):,} rows, {prices.symbol.nunique()} symbols\n")

    print("── earnings ──", flush=True)
    earnings, coverage = fetch_earnings(symbols)
    earnings.to_csv(out_dir / "earnings.csv", index=False)
    coverage.to_csv(out_dir / "earnings_coverage.csv", index=False)
    print(f"\nearnings: {len(earnings):,} dates across "
          f"{earnings.symbol.nunique() if len(earnings) else 0} symbols")


if __name__ == "__main__":
    asyncio.run(main())
