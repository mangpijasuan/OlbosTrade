"""Tests for Trade Journal Intelligence."""

from __future__ import annotations

from datetime import date, datetime

from app.services.journal_intelligence import analyze, _best_worst, _to_date


def test_best_worst_empty_and_nonempty():
    assert _best_worst({}) == (None, None)
    stats = {"a": {"expectancy": 10}, "b": {"expectancy": -5}}
    assert _best_worst(stats) == ("a", "b")


def _t(pnl, strategy="bull_put_spread", regime="normal_mean_revert",
       score=0.8, entry="2024-01-01", exit_="2024-01-05"):
    return {"pnl": pnl, "strategy": strategy, "regime": regime, "signal_score": score,
            "entry_date": entry, "exit_date": exit_}


def test_to_date_types():
    assert _to_date(None) is None
    assert _to_date(date(2024, 1, 2)) == date(2024, 1, 2)
    assert _to_date(datetime(2024, 1, 2, 9)) == date(2024, 1, 2)
    assert _to_date("2024-01-02") == date(2024, 1, 2)
    assert _to_date("garbage") is None


def test_empty_report():
    r = analyze([])
    assert r["total_trades"] == 0 and r["insights"] == ["No closed trades yet."]


def test_skips_none_pnl():
    r = analyze([{"pnl": None}])
    assert r["total_trades"] == 0


def test_buckets_and_best_worst():
    trades = (
        [_t(100, strategy="bull_put_spread") for _ in range(5)]
        + [_t(-80, strategy="iron_condor") for _ in range(5)]
    )
    r = analyze(trades)
    assert r["total_trades"] == 10
    assert r["best_strategy"] == "bull_put_spread"
    assert r["worst_strategy"] == "iron_condor"
    assert r["by_strategy"]["bull_put_spread"]["win_rate"] == 1.0
    assert r["by_strategy"]["iron_condor"]["expectancy"] == -80.0


def test_hold_time_winners_vs_losers():
    trades = [_t(100, entry="2024-01-01", exit_="2024-01-03"),    # 2d winner
              _t(-50, entry="2024-01-01", exit_="2024-01-11")]    # 10d loser
    r = analyze(trades)
    assert r["hold_time"]["avg_winner_days"] == 2.0
    assert r["hold_time"]["avg_loser_days"] == 10.0
    assert any("held longer" in i for i in r["insights"])


def test_signal_score_separation_insight():
    trades = [_t(100, score=0.9), _t(100, score=0.9), _t(-50, score=0.4)]
    r = analyze(trades)
    assert r["signal_score"]["avg_winner_score"] == 0.9
    assert any("ranker is informative" in i for i in r["insights"])


def test_signal_score_not_separating():
    trades = [_t(100, score=0.3), _t(-50, score=0.9), _t(-50, score=0.9)]
    r = analyze(trades)
    assert any("does NOT separate" in i for i in r["insights"])


def test_recurring_losing_setup_detected():
    trades = [_t(-30, strategy="iron_condor", regime="high_vol_trending") for _ in range(4)]
    r = analyze(trades, min_setup_sample=3)
    assert r["recurring_losing_setups"]
    top = r["recurring_losing_setups"][0]
    assert top["strategy"] == "iron_condor" and top["regime"] == "high_vol_trending"
    assert any("Recurring losing setup" in i for i in r["insights"])


def test_no_recurring_when_below_sample():
    trades = [_t(-30, strategy="iron_condor") for _ in range(2)]
    r = analyze(trades, min_setup_sample=3)
    assert r["recurring_losing_setups"] == []


def test_missing_dates_and_scores_tolerated():
    r = analyze([{"pnl": 100, "strategy": "x"}, {"pnl": -20, "strategy": "x"}])
    assert r["total_trades"] == 2
    assert r["hold_time"]["avg_winner_days"] is None
    assert r["signal_score"]["avg_winner_score"] is None


def test_best_worst_regime_insight():
    trades = ([_t(100, regime="normal_mean_revert") for _ in range(4)]
              + [_t(-60, regime="high_vol_trending") for _ in range(4)])
    r = analyze(trades)
    assert r["best_regime"] == "normal_mean_revert"
    assert r["worst_regime"] == "high_vol_trending"
    assert any("Best regime to trade" in i for i in r["insights"])


def test_winner_held_longer_no_stop_insight():
    # winner held longer than loser → the "tighten stops" insight is NOT emitted
    trades = [_t(100, entry="2024-01-01", exit_="2024-01-11"),   # 10d winner
              _t(-50, entry="2024-01-01", exit_="2024-01-03")]   # 2d loser
    r = analyze(trades)
    assert not any("held longer" in i for i in r["insights"])


def test_insights_fallback_when_flat():
    # single bucket, no date/score signal → fallback insight
    r = analyze([{"pnl": 10, "strategy": "x", "regime": "r"}])
    assert isinstance(r["insights"], list) and r["insights"]
