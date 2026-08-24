"""
Unit tests for the rotation-scoped correlation cluster cache — the read
API position_rotation.py's tiebreaker depends on must distinguish "never
seen this ticker" (None, no signal) from "covered but not clustered"
(False, real signal), and must never present stale data as fresh.
"""

from __future__ import annotations

import time

import pytest

from app.services import rotation_correlation_cache as cache


@pytest.fixture(autouse=True)
def _reset_cache():
    cache.clear()
    yield
    cache.clear()


def _cluster(tickers: list[str], avg_correlation: float = 0.9) -> dict:
    return {
        "tickers": tickers,
        "avg_correlation": avg_correlation,
        "combined_risk_dollars": 10_000.0,
        "pct_of_capital": 45.0,
    }


def test_empty_cache_returns_none_for_any_ticker():
    assert cache.in_flagged_cluster("AAPL") is None


def test_flagged_ticker_returns_true():
    cache._store(
        flagged_clusters=[_cluster(["AAPL", "MSFT"])],
        covered_tickers={"AAPL", "MSFT", "NVDA"},
    )
    assert cache.in_flagged_cluster("AAPL") is True
    assert cache.in_flagged_cluster("MSFT") is True


def test_covered_not_flagged_returns_false():
    cache._store(
        flagged_clusters=[_cluster(["AAPL", "MSFT"])],
        covered_tickers={"AAPL", "MSFT", "NVDA"},
    )
    assert cache.in_flagged_cluster("NVDA") is False


def test_uncovered_ticker_returns_none():
    cache._store(
        flagged_clusters=[_cluster(["AAPL", "MSFT"])],
        covered_tickers={"AAPL", "MSFT"},
    )
    assert cache.in_flagged_cluster("TSLA") is None


def test_stale_cache_returns_none_even_for_previously_flagged_ticker(monkeypatch):
    monkeypatch.setattr(cache, "STALE_AFTER_S", 0.02)
    cache._store(
        flagged_clusters=[_cluster(["AAPL", "MSFT"])],
        covered_tickers={"AAPL", "MSFT"},
    )
    assert cache.in_flagged_cluster("AAPL") is True
    time.sleep(0.05)
    assert cache.in_flagged_cluster("AAPL") is None


def test_case_insensitive_lookup():
    cache._store(
        flagged_clusters=[_cluster(["AAPL"])],
        covered_tickers={"AAPL"},
    )
    assert cache.in_flagged_cluster("aapl") is True


def test_clear_resets_all_state():
    cache._store(
        flagged_clusters=[_cluster(["AAPL"])],
        covered_tickers={"AAPL"},
    )
    cache.clear()
    assert cache.in_flagged_cluster("AAPL") is None
