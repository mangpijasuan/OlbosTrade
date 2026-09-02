"""Pure-aggregation tests for the rotation-performance ledger."""

from __future__ import annotations

from app.services.rotation_ledger import compute_rotation_ledger_stats


def _row(ticker, pnl, regime="normal_mean_revert", entry="2026-08-01",
         exit="2026-08-03", hold_days=2, exit_reason="position_rotation"):
    return {
        "trade_id": f"{ticker}-{exit}", "ticker": ticker, "pnl": pnl,
        "regime": regime, "entry_date": entry, "exit_date": exit,
        "hold_days": hold_days, "exit_reason": exit_reason,
    }


def test_empty_list_returns_zeroed_stats():
    stats = compute_rotation_ledger_stats([])
    assert stats["total"] == 0
    assert stats["total_pnl"] == 0
    assert stats["avg_pnl"] is None
    assert stats["win_rate"] is None
    assert stats["avg_hold_days"] is None
    assert stats["by_regime"] == {}
    assert stats["recent"] == []


def test_single_win():
    stats = compute_rotation_ledger_stats([_row("AAPL", 50.0)])
    assert stats["total"] == 1
    assert stats["total_pnl"] == 50.0
    assert stats["avg_pnl"] == 50.0
    assert stats["win_rate"] == 1.0


def test_single_loss():
    stats = compute_rotation_ledger_stats([_row("AAPL", -20.0)])
    assert stats["total"] == 1
    assert stats["total_pnl"] == -20.0
    assert stats["win_rate"] == 0.0


def test_mixed_win_rate_math():
    rows = [_row("A", 10.0), _row("B", -5.0), _row("C", 20.0), _row("D", -1.0)]
    stats = compute_rotation_ledger_stats(rows)
    assert stats["total"] == 4
    assert stats["total_pnl"] == 24.0
    assert stats["avg_pnl"] == 6.0
    assert stats["win_rate"] == 0.5


def test_avg_hold_days():
    rows = [_row("A", 10.0, hold_days=1), _row("B", -5.0, hold_days=3)]
    stats = compute_rotation_ledger_stats(rows)
    assert stats["avg_hold_days"] == 2.0


def test_by_regime_split():
    rows = [
        _row("A", 10.0, regime="low_vol_trending"),
        _row("B", -5.0, regime="low_vol_trending"),
        _row("C", 20.0, regime="high_vol_trending"),
    ]
    stats = compute_rotation_ledger_stats(rows)
    assert set(stats["by_regime"].keys()) == {"low_vol_trending", "high_vol_trending"}
    assert stats["by_regime"]["low_vol_trending"]["total"] == 2
    assert stats["by_regime"]["low_vol_trending"]["total_pnl"] == 5.0
    assert stats["by_regime"]["high_vol_trending"]["total"] == 1
    assert stats["by_regime"]["high_vol_trending"]["win_rate"] == 1.0


def test_by_regime_excludes_missing_regime():
    rows = [_row("A", 10.0, regime=None), _row("B", -5.0, regime="unknown")]
    stats = compute_rotation_ledger_stats(rows)
    assert set(stats["by_regime"].keys()) == {"unknown"}


def test_recent_sorted_descending_by_exit_date():
    rows = [
        _row("OLD", 5.0, exit="2026-08-01"),
        _row("NEW", 10.0, exit="2026-08-10"),
        _row("MID", -2.0, exit="2026-08-05"),
    ]
    stats = compute_rotation_ledger_stats(rows)
    assert [r["ticker"] for r in stats["recent"]] == ["NEW", "MID", "OLD"]


def test_recent_capped_at_limit():
    rows = [_row(f"T{i}", 1.0, exit=f"2026-08-{i:02d}") for i in range(1, 30)]
    stats = compute_rotation_ledger_stats(rows)
    assert len(stats["recent"]) == 20
    assert stats["recent"][0]["ticker"] == "T29"  # newest exit_date first
