"""
Unit tests for DataFetcher.
Run with: pytest tests/test_data_fetcher.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.services.data_fetcher import DataFetcher


@pytest.fixture
def mock_broker():
    return AsyncMock()


@pytest.fixture
def fetcher(mock_broker):
    return DataFetcher(broker=mock_broker)


def make_close_series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


# ── fetch_ohlcv ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_dataframe(fetcher):
    mock_df = pd.DataFrame({
        "Open":  [450.0] * 30,
        "High":  [455.0] * 30,
        "Low":   [448.0] * 30,
        "Close": [452.0] * 30,
        "Volume": [50_000_000] * 30,
    }, index=pd.date_range("2024-01-01", periods=30))

    with patch("app.services.data_fetcher.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = mock_df
        df = await fetcher.fetch_ohlcv("SPY", "2024-01-01", "2024-01-30")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 30
    assert "Close" in df.columns


@pytest.mark.asyncio
async def test_fetch_ohlcv_raises_on_empty(fetcher):
    with patch("app.services.data_fetcher.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        with pytest.raises(ValueError, match="No OHLCV data"):
            await fetcher.fetch_ohlcv("FAKE", "2024-01-01", "2024-01-30")


# ── IV Rank ──────────────────────────────────────────────────────────────────

class TestIVRank:
    def test_iv_rank_at_max(self, fetcher):
        iv = make_close_series([0.10, 0.15, 0.20, 0.25, 0.30])
        assert fetcher.calculate_iv_rank(iv) == pytest.approx(100.0)

    def test_iv_rank_at_min(self, fetcher):
        iv = make_close_series([0.30, 0.25, 0.20, 0.15, 0.10])
        assert fetcher.calculate_iv_rank(iv) == pytest.approx(0.0)

    def test_iv_rank_midpoint(self, fetcher):
        iv = make_close_series([0.10, 0.20, 0.30, 0.20])
        rank = fetcher.calculate_iv_rank(iv)
        assert 40 < rank < 60  # current (0.20) is mid of range 0.10–0.30

    def test_iv_rank_zero_range_returns_zero(self, fetcher):
        iv = make_close_series([0.20, 0.20, 0.20])
        assert fetcher.calculate_iv_rank(iv) == 0.0

    def test_iv_rank_single_value(self, fetcher):
        iv = make_close_series([0.20])
        assert fetcher.calculate_iv_rank(iv) == 0.0


# ── IV Percentile ─────────────────────────────────────────────────────────────

class TestIVPercentile:
    def test_iv_percentile_all_below(self, fetcher):
        iv = make_close_series([0.10, 0.12, 0.14, 0.16, 0.20])
        pct = fetcher.calculate_iv_percentile(iv)
        assert pct == pytest.approx(80.0)  # 4 out of 5 values below 0.20

    def test_iv_percentile_all_above(self, fetcher):
        iv = make_close_series([0.30, 0.28, 0.26, 0.24, 0.10])
        pct = fetcher.calculate_iv_percentile(iv)
        assert pct == pytest.approx(0.0)

    def test_iv_percentile_midrange(self, fetcher):
        iv = make_close_series([0.10, 0.15, 0.20, 0.25, 0.30, 0.20])
        pct = fetcher.calculate_iv_percentile(iv)
        assert 30 < pct < 70
