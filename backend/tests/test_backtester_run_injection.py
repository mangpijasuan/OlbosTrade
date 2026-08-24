"""
Tests for Backtester.run()'s new optional strategy_params/spy_df injection
(Track 2D) — confirms the pre-fetch-and-reuse pattern strategy_optimizer.py
depends on is behavior-preserving: passing spy_df in must produce the exact
same BacktestResult as letting run() fetch it internally, given the same
underlying data either way.

Like test_backtester_run_equity.py, this exercises backtester.py directly
with a synthetic DataFetcher — no live network calls. backtester.py
transitively imports SQLAlchemy models (via data_fetcher.py), which trips
the local py3.9 SQLAlchemy-annotation wall — CI (py3.11) is the source of
truth here, matching the existing constraint for the rest of this suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from app.services.backtester import Backtester, BacktestResult
from app.services.data_fetcher import DataFetcher
from app.services.strategy_engine import StrategyExitParams


class _SyntheticDataFetcher(DataFetcher):
    """
    Real DataFetcher subclass, not a duck-typed stand-in — Backtester.run()
    (the options path) calls self.fetcher.calculate_rsi()/calculate_sma()/
    calculate_realized_vol() directly (unlike run_equity(), which uses its
    own indicator functions), so a fetch_ohlcv-only fake is insufficient
    here. Only fetch_ohlcv is overridden, to avoid real network/broker
    calls; the calculate_* methods are pure pandas math with no I/O, so
    inheriting them is safe.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        super().__init__(broker=MagicMock())
        self._df = df

    async def fetch_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        mask = (self._df.index >= pd.Timestamp(start)) & (self._df.index <= pd.Timestamp(end))
        return self._df.loc[mask].copy()


def _synthetic_ohlcv(n_days: int = 400, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    returns = rng.normal(loc=0.0002, scale=0.012, size=n_days)
    close = 400 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0.004, 0.003, n_days)))
    low = close * (1 - np.abs(rng.normal(0.004, 0.003, n_days)))
    open_ = close * (1 + rng.normal(0, 0.002, n_days))
    volume = rng.integers(1_000_000, 5_000_000, n_days)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


def _synthetic_vix(n_days: int = 400, seed: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    close = 18 + rng.normal(0, 2.0, n_days).cumsum() * 0.05
    return pd.DataFrame({"Close": np.clip(close, 10, 40)}, index=dates)


@pytest.fixture
def fetcher():
    return _SyntheticDataFetcher(_synthetic_ohlcv())


@pytest.fixture
def vix_df():
    return _synthetic_vix()


@pytest.mark.asyncio
async def test_spy_df_injection_matches_internal_fetch(fetcher, vix_df):
    """Two separate Backtester instances (not one instance called twice) —
    FillSimulator's RNG is seeded once at construction (random_seed=42) and
    advances across calls on the same instance, so two sequential .run()
    calls on one Backtester would draw different random fills purely from
    call order, independent of the spy_df injection being tested here."""
    start, end = "2023-06-01", "2023-11-30"
    warmup_start = (pd.Timestamp(start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")

    internal_result = await Backtester(fetcher).run(
        "bull_put_spread", start, end, starting_capital=25_000.0, vix_df=vix_df,
    )

    pre_fetched = await fetcher.fetch_ohlcv("SPY", warmup_start, end)
    injected_result = await Backtester(fetcher).run(
        "bull_put_spread", start, end, starting_capital=25_000.0,
        vix_df=vix_df, spy_df=pre_fetched,
    )

    assert isinstance(internal_result, BacktestResult)
    assert isinstance(injected_result, BacktestResult)
    assert injected_result.ending_capital == internal_result.ending_capital
    assert len(injected_result.trades) == len(internal_result.trades)
    assert injected_result.equity_curve == internal_result.equity_curve


@pytest.mark.asyncio
async def test_strategy_params_injection_changes_result(fetcher, vix_df):
    """A non-default StrategyExitParams must actually change the backtest
    (proves the param is really threaded through to the strategy, not
    silently ignored)."""
    start, end = "2023-06-01", "2023-11-30"

    default_result = await Backtester(fetcher).run(
        "bull_put_spread", start, end, starting_capital=25_000.0, vix_df=vix_df,
    )
    tight_result = await Backtester(fetcher).run(
        "bull_put_spread", start, end, starting_capital=25_000.0, vix_df=vix_df,
        strategy_params=StrategyExitParams(profit_target_pct=0.10, dte_exit=25),
    )

    # A much tighter profit target / earlier DTE exit should change at
    # least one of: trade count, exit reasons, or ending capital — some
    # observable difference proving the params were actually used.
    default_exit_reasons = [t.exit_reason for t in default_result.trades]
    tight_exit_reasons = [t.exit_reason for t in tight_result.trades]
    assert (
        tight_result.ending_capital != default_result.ending_capital
        or len(tight_result.trades) != len(default_result.trades)
        or tight_exit_reasons != default_exit_reasons
    )
