"""Tests for the frozen daily top-3 snapshot.

The value of this table is entirely in what it refuses to do. Ranking is pure
and lives in `rank_candidates`, so the rules that keep the record honest can
be tested without a database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.daily_signal_snapshot import BUY, SELL, rank_candidates

T0 = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)


def _c(ticker, action=BUY, score=50, minutes=0):
    return {"ticker": ticker, "action": action, "opportunity_score": score,
            "generated_at": T0 + timedelta(minutes=minutes)}


def test_takes_top_three_per_side_by_opportunity_score():
    rows = [_c("AAA", BUY, 90), _c("BBB", BUY, 80), _c("CCC", BUY, 70),
            _c("DDD", BUY, 60), _c("EEE", SELL, 95), _c("FFF", SELL, 55)]
    out = rank_candidates(rows)
    assert [c["ticker"] for c in out[BUY]] == ["AAA", "BBB", "CCC"]
    assert [c["ticker"] for c in out[SELL]] == ["EEE", "FFF"]


def test_dedupes_to_the_earliest_appearance_not_the_best_score():
    """The core anti-hindsight rule. The scanner re-records the same signal
    ~45 times as it re-scores; keeping the best-scoring version would let a
    late re-score that already knows how the morning went inflate the record."""
    rows = [
        _c("NVDA", BUY, score=40, minutes=0),    # first appearance, modest
        _c("NVDA", BUY, score=99, minutes=180),  # re-scored after the move
        _c("AAA", BUY, score=60, minutes=5),
    ]
    out = rank_candidates(rows)
    # AAA outranks NVDA because NVDA is judged on its 09:xx score of 40,
    # not the 99 it earned three hours later.
    assert [c["ticker"] for c in out[BUY]] == ["AAA", "NVDA"]
    assert out[BUY][1]["opportunity_score"] == 40


def test_buy_and_sell_are_ranked_independently():
    # Same ticker can legitimately appear on both sides across a session.
    rows = [_c("SPY", BUY, 70, 0), _c("SPY", SELL, 85, 60)]
    out = rank_candidates(rows)
    assert [c["ticker"] for c in out[BUY]] == ["SPY"]
    assert [c["ticker"] for c in out[SELL]] == ["SPY"]
    assert out[SELL][0]["opportunity_score"] == 85


def test_unscored_signals_are_excluded_not_treated_as_zero():
    """A missing score is not a low score. A signal the desk never scored was
    never ranked, and padding the top 3 with one would be an invention."""
    rows = [_c("AAA", BUY, 30), {"ticker": "BBB", "action": BUY,
                                 "opportunity_score": None, "generated_at": T0}]
    out = rank_candidates(rows)
    assert [c["ticker"] for c in out[BUY]] == ["AAA"]


def test_a_side_with_nothing_returns_empty_not_padded():
    out = rank_candidates([_c("AAA", BUY, 50)])
    assert len(out[BUY]) == 1
    assert out[SELL] == []


def test_fewer_than_three_is_reported_as_it_is():
    # Two real signals must not become three by borrowing from the other side.
    out = rank_candidates([_c("AAA", BUY, 50), _c("BBB", BUY, 40)])
    assert len(out[BUY]) == 2


def test_ties_break_deterministically_by_ticker():
    # Two captures of the same day must produce the same ordering, or the
    # "frozen" record is not reproducible.
    rows = [_c("ZZZ", BUY, 70, 0), _c("AAA", BUY, 70, 1)]
    assert [c["ticker"] for c in rank_candidates(rows)[BUY]] == ["AAA", "ZZZ"]
    assert [c["ticker"] for c in rank_candidates(list(reversed(rows)))[BUY]] == ["AAA", "ZZZ"]


def test_ignores_rows_with_no_ticker_or_a_non_directional_action():
    rows = [_c("AAA", BUY, 50), _c("", BUY, 99),
            {"ticker": "HOLDME", "action": "HOLD", "opportunity_score": 99,
             "generated_at": T0}]
    out = rank_candidates(rows)
    assert [c["ticker"] for c in out[BUY]] == ["AAA"]
    assert out[SELL] == []
