"""
A performance figure computed over part of the book must say so.

Eight production trades (July 2026, exit_reason "closed_price_unavailable")
left the broker before any execution price arrived. Their P&L is
unrecoverable, so they cannot be counted — but they were being dropped
silently, which made win rate, profit factor and total P&L read as though
they covered every closed trade. These tests pin the disclosure, not the
arithmetic.
"""
from datetime import date

from app.services.performance_analytics import compute_performance

CAPITAL = 25_000.0


def _t(pnl, entry="2026-07-01", exit_="2026-07-10"):
    return {
        "pnl": pnl,
        "entry_date": date.fromisoformat(entry),
        "exit_date": date.fromisoformat(exit_),
    }


def test_complete_book_reports_no_incompleteness():
    out = compute_performance([_t(100.0), _t(-50.0)], CAPITAL)
    assert out["unmeasured_trades"] == 0
    assert out["measured_pct"] == 100.0
    assert out["performance_incomplete"] is False


def test_unmeasured_trades_are_counted_and_flagged():
    trades = [_t(100.0), _t(-50.0), _t(None), _t(None)]
    out = compute_performance(trades, CAPITAL)
    assert out["unmeasured_trades"] == 2
    assert out["measured_pct"] == 50.0
    assert out["performance_incomplete"] is True


def test_the_ratios_still_describe_only_the_measured_subset():
    # The disclosure is additive — it must not change the arithmetic, or
    # every historical figure silently shifts meaning.
    measured = [_t(100.0), _t(-50.0)]
    a = compute_performance(measured, CAPITAL)
    b = compute_performance(measured + [_t(None)], CAPITAL)
    for key in ("total_trades", "wins", "losses", "win_rate",
                "total_pnl", "profit_factor", "expectancy"):
        assert a[key] == b[key], key


def test_total_trades_counts_measured_not_submitted():
    out = compute_performance([_t(100.0), _t(None), _t(None)], CAPITAL)
    assert out["total_trades"] == 1
    assert out["unmeasured_trades"] == 2


def test_an_all_unmeasured_book_does_not_read_as_a_desk_that_never_traded():
    # The regression that matters most: 8 trades in, no P&L on any of them,
    # must not be indistinguishable from an empty book.
    out = compute_performance([_t(None) for _ in range(8)], CAPITAL)
    assert out["unmeasured_trades"] == 8
    assert out["measured_pct"] == 0.0
    assert out["performance_incomplete"] is True
    assert out["total_trades"] == 0


def test_a_genuinely_empty_book_is_not_flagged_incomplete():
    out = compute_performance([], CAPITAL)
    assert out["unmeasured_trades"] == 0
    assert out["measured_pct"] == 100.0
    assert out["performance_incomplete"] is False
