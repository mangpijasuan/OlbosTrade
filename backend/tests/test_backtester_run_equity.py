"""
Tests for Backtester.run_equity() — the walk-forward equity backtest that
reuses the live equity_signal_engine functions and GuardrailEngine instead
of a parallel DSL.

Like test_quant_research.py, this exercises backtester.py end-to-end with a
synthetic DataFetcher — no live network/broker calls, deterministic seed.
Note: backtester.py transitively imports SQLAlchemy models (via
data_fetcher.py), which trips the local py3.9 SQLAlchemy-annotation wall —
this module runs on CI (py3.11) as the source of truth, matching the
existing constraint documented for the rest of this test suite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.backtester import Backtester, BacktestResult


class _FakeFetcher:
    """Duck-typed stand-in for DataFetcher — only fetch_ohlcv is used by
    run_equity(). Returns a synthetic, seeded random-walk OHLCV series so
    the real ta-based indicators have real variation to work with."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    async def fetch_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        mask = (self._df.index >= pd.Timestamp(start)) & (self._df.index <= pd.Timestamp(end))
        return self._df.loc[mask].copy()


def _synthetic_ohlcv(n_days: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    # Random walk with slight upward drift so both long and short setups
    # have a chance to fire across the series.
    returns = rng.normal(loc=0.0003, scale=0.015, size=n_days)
    close = 100 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0.004, 0.003, n_days)))
    low = close * (1 - np.abs(rng.normal(0.004, 0.003, n_days)))
    open_ = close * (1 + rng.normal(0, 0.002, n_days))
    volume = rng.integers(1_000_000, 5_000_000, n_days)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


@pytest.fixture
def fetcher():
    return _FakeFetcher(_synthetic_ohlcv())


@pytest.mark.asyncio
async def test_run_equity_returns_result_shaped_for_existing_ui(fetcher):
    bt = Backtester(fetcher)
    result = await bt.run_equity("AAPL", "2023-06-01", "2023-12-29", starting_capital=25_000.0)

    assert isinstance(result, BacktestResult)
    assert result.strategy == "equity:AAPL"
    assert result.starting_capital == 25_000.0
    assert result.metrics is not None
    assert result.equity_curve[0] == 25_000.0


@pytest.mark.asyncio
async def test_run_equity_trades_belong_to_the_requested_ticker(fetcher):
    bt = Backtester(fetcher)
    result = await bt.run_equity("AAPL", "2023-06-01", "2023-12-29")

    for t in result.trades:
        assert t.underlying == "AAPL"
        assert t.strategy == "equity"
        assert t.direction in ("BUY", "SELL")
        assert t.contracts > 0  # share count
        assert t.entry_price is not None and t.entry_price > 0


@pytest.mark.asyncio
async def test_run_equity_positions_never_overlap(fetcher):
    """Regression test: one position at a time — a same-bar exit must not
    be immediately followed by a same-bar re-entry (that would predate the
    exit that freed the position up, since the exit is decided from
    intrabar high/low while entry fills at the bar's open)."""
    bt = Backtester(fetcher)
    result = await bt.run_equity("AAPL", "2023-01-01", "2023-12-29")

    closed = [t for t in result.trades if t.exit_reason != "backtest_end"]
    closed.sort(key=lambda t: t.entry_date)
    for prev, cur in zip(closed, closed[1:]):
        assert prev.exit_date is not None
        assert cur.entry_date > prev.exit_date


@pytest.mark.asyncio
async def test_run_equity_entry_never_after_exit(fetcher):
    bt = Backtester(fetcher)
    result = await bt.run_equity("AAPL", "2023-01-01", "2023-12-29")

    for t in result.trades:
        if t.exit_date is not None and t.entry_date is not None:
            assert t.exit_date >= t.entry_date


@pytest.mark.asyncio
async def test_run_equity_bar_log_has_one_entry_per_bar_with_expected_shape(fetcher):
    bt = Backtester(fetcher)
    result = await bt.run_equity("AAPL", "2023-06-01", "2023-12-29")

    assert len(result.bar_log) > 0
    for entry in result.bar_log:
        assert set(entry.keys()) == {
            "date", "close", "indicators", "action", "confidence",
            "trade_fired", "position_open", "portfolio_value",
        }
        assert entry["action"] in ("BUY", "SELL", "HOLD")
        if entry["indicators"] is not None:
            assert set(entry["indicators"].keys()) == {
                "rsi", "macd", "bb_pct_b", "atr", "volume_ratio",
            }
        else:
            # No indicators (not enough warmup window) means nothing could
            # have fired that bar.
            assert entry["trade_fired"] is False


@pytest.mark.asyncio
async def test_run_equity_bar_log_trade_fired_matches_an_actual_entry(fetcher):
    """Every bar flagged trade_fired must correspond to a real trade whose
    entry_date is that bar's date — the log must not claim a fill that
    never happened."""
    bt = Backtester(fetcher)
    result = await bt.run_equity("AAPL", "2023-01-01", "2023-12-29")

    entry_dates = {t.entry_date.isoformat() for t in result.trades}
    fired_dates = {e["date"] for e in result.bar_log if e["trade_fired"]}
    assert fired_dates.issubset(entry_dates)


@pytest.mark.asyncio
async def test_run_equity_raises_on_empty_data():
    empty_df = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"],
        index=pd.DatetimeIndex([]),
    )
    empty_fetcher = _FakeFetcher(empty_df)
    bt = Backtester(empty_fetcher)
    with pytest.raises(ValueError):
        await bt.run_equity("ZZZZ", "2023-01-01", "2023-12-29")
