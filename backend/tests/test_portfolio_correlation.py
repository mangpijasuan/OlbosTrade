"""Tests for the correlation-clustering pure functions in portfolio_engine.py."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from app.services.portfolio_engine import (
    align_price_series,
    cluster_concentration_flags,
    compute_correlation_clusters,
)

BASE = datetime(2026, 1, 1)


def _bars(values, start=BASE, step_days=1):
    return [NS(timestamp=start + timedelta(days=i * step_days), close=v) for i, v in enumerate(values)]


# ── align_price_series ──────────────────────────────────────────────────────

def test_align_intersects_mismatched_calendars():
    a = _bars([100 + i for i in range(35)], start=BASE)
    # B starts 5 days later — only the overlapping tail should be aligned.
    b = _bars([200 + i for i in range(35)], start=BASE + timedelta(days=5))
    aligned, excluded = align_price_series({"A": a, "B": b}, min_bars=20)
    assert excluded == []
    assert len(aligned["A"]) == len(aligned["B"])
    assert len(aligned["A"]) == 30  # 35 - 5 days overlap


def test_align_excludes_thin_ticker():
    a = _bars([100 + i for i in range(35)])
    thin = _bars([1, 2, 3])
    aligned, excluded = align_price_series({"A": a, "THIN": thin}, min_bars=30)
    assert aligned == {}
    assert excluded == [{"ticker": "THIN", "reason": "only 3 bars, need >= 30"}]


def test_align_insufficient_overlap_after_intersection():
    a = _bars([100 + i for i in range(30)], start=BASE)
    b = _bars([200 + i for i in range(30)], start=BASE + timedelta(days=25))
    aligned, excluded = align_price_series({"A": a, "B": b}, min_bars=30)
    assert aligned == {}
    reasons = {e["ticker"]: e["reason"] for e in excluded}
    assert "overlapping trading days" in reasons["A"]
    assert "overlapping trading days" in reasons["B"]


def test_align_single_ticker_returns_empty():
    a = _bars([100 + i for i in range(35)])
    aligned, excluded = align_price_series({"A": a}, min_bars=30)
    assert aligned == {}
    assert excluded == []


# ── compute_correlation_clusters ────────────────────────────────────────────

def test_perfectly_correlated_pair_clusters():
    a = [100 + i for i in range(40)]
    b = [200 + 2 * i for i in range(40)]  # exactly 2x A's moves
    result = compute_correlation_clusters({"A": a, "B": b}, threshold=0.70)
    assert result["clusters"] == [{"tickers": ["A", "B"], "avg_correlation": 1.0}]
    assert result["correlation_matrix"]["A"]["B"] == 1.0


def test_uncorrelated_pair_does_not_cluster():
    a = [100 + (i % 2) * 3 for i in range(40)]          # oscillating
    b = [50 + ((i + 1) % 2) * 3 for i in range(40)]     # inverse oscillation
    result = compute_correlation_clusters({"A": a, "B": b}, threshold=0.70)
    assert result["clusters"] == []


def test_three_way_transitive_correlation_is_one_cluster():
    a = [100 + i for i in range(40)]
    b = [200 + 2 * i for i in range(40)]
    c = [50 + 0.5 * i for i in range(40)]
    result = compute_correlation_clusters({"A": a, "B": b, "C": c}, threshold=0.70)
    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["tickers"] == ["A", "B", "C"]


def test_two_independent_pairs_stay_separate():
    import random
    random.seed(42)
    a = [100 + i for i in range(40)]
    b = [200 + 2 * i for i in range(40)]
    # C/D move together but unrelated to A/B (alternating pattern).
    c = [80 + (i % 5) for i in range(40)]
    d = [40 + 3 * (i % 5) for i in range(40)]
    result = compute_correlation_clusters({"A": a, "B": b, "C": c, "D": d}, threshold=0.70)
    cluster_sets = [set(cl["tickers"]) for cl in result["clusters"]]
    assert {"A", "B"} in cluster_sets
    assert {"C", "D"} in cluster_sets
    assert len(result["clusters"]) == 2


def test_single_ticker_no_crash_empty_clusters():
    result = compute_correlation_clusters({"A": [100 + i for i in range(40)]})
    assert result["clusters"] == []
    assert result["tickers"] == ["A"]
    assert result["correlation_matrix"] == {}


def test_negative_correlation_never_clusters():
    """Signed threshold: a hedge (exactly-inverse daily returns) must not be
    flagged as a concentration cluster — that would invert the actual risk
    signal (negative correlation is diversification, not concentration)."""
    rets = [0.01, -0.02, 0.015, -0.01, 0.03, -0.025, 0.005, -0.015] * 5
    a = [100.0]
    b = [100.0]
    for r in rets:
        a.append(a[-1] * (1 + r))
        b.append(b[-1] * (1 - r))  # exactly opposite daily return
    result = compute_correlation_clusters({"A": a, "B": b}, threshold=0.70)
    assert result["correlation_matrix"]["A"]["B"] < -0.9
    assert result["clusters"] == []


# ── cluster_concentration_flags ─────────────────────────────────────────────

def test_over_threshold_cluster_produces_flag():
    clusters = [{"tickers": ["A", "B"], "avg_correlation": 0.95}]
    enriched, flags = cluster_concentration_flags(
        clusters, {"A": 6000.0, "B": 5000.0}, capital=20000.0, max_cluster_pct=0.40
    )
    assert enriched[0]["combined_risk_dollars"] == 11000.0
    assert enriched[0]["pct_of_capital"] == 55.0
    assert flags == ["correlation_concentration:A+B 55%>40%"]


def test_under_threshold_cluster_produces_no_flag():
    clusters = [{"tickers": ["A", "B"], "avg_correlation": 0.85}]
    enriched, flags = cluster_concentration_flags(
        clusters, {"A": 1000.0, "B": 1000.0}, capital=20000.0, max_cluster_pct=0.40
    )
    assert enriched[0]["pct_of_capital"] == 10.0
    assert flags == []


def test_zero_capital_safe():
    clusters = [{"tickers": ["A", "B"], "avg_correlation": 0.95}]
    enriched, flags = cluster_concentration_flags(clusters, {"A": 1000.0, "B": 1000.0}, capital=0.0)
    assert enriched[0]["pct_of_capital"] == 0.0
    assert flags == []
