"""
Regression coverage for the background equity scanner's watchlist rotation.

ARCHITECTURE_AUDIT.md finding #5: main.py's background scan always took
watchlist[:5] — with the 13-symbol charter watchlist and a 5-per-tick cap,
8 symbols (everything past AAPL/NVDA/MSFT/META/AMZN) were never scanned by
autopilot at all, silently. _rotate_watchlist_window replaces the static
slice with a rotating window so every symbol gets scanned over time.
"""
from __future__ import annotations

import app.main as m


def test_first_window_starts_at_offset_zero():
    watchlist = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "GOOGL", "AMD"]
    window, next_offset = m._rotate_watchlist_window(watchlist, 0)
    assert window == ["AAPL", "NVDA", "MSFT", "META", "AMZN"]
    assert next_offset == 5


def test_next_tick_advances_past_previous_window():
    watchlist = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "GOOGL", "AMD"]
    window, next_offset = m._rotate_watchlist_window(watchlist, 5)
    assert window == ["GOOGL", "AMD", "AAPL", "NVDA", "MSFT"]
    assert next_offset == 10


def test_wraps_around_end_of_watchlist():
    # 13-symbol charter watchlist, offset 10 -> wraps after index 12
    watchlist = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "GOOGL", "AMD",
                 "TSLA", "SPY", "QQQ", "JPM", "V", "MA"]
    window, next_offset = m._rotate_watchlist_window(watchlist, 10)
    assert window == ["JPM", "V", "MA", "AAPL", "NVDA"]
    assert next_offset == 15


def test_all_symbols_get_scanned_across_full_rotation():
    watchlist = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "GOOGL", "AMD",
                 "TSLA", "SPY", "QQQ", "JPM", "V", "MA"]
    seen: set = set()
    offset = 0
    for _ in range(len(watchlist)):   # gcd(5, 13) == 1 -> covers all in n ticks
        window, offset = m._rotate_watchlist_window(watchlist, offset)
        seen.update(window)
    assert seen == set(watchlist)


def test_window_shorter_than_size_when_watchlist_smaller():
    watchlist = ["AAPL", "NVDA", "MSFT"]
    window, next_offset = m._rotate_watchlist_window(watchlist, 0)
    assert window == ["AAPL", "NVDA", "MSFT"]   # no duplicates, capped at len
    assert next_offset == 5


def test_empty_watchlist_returns_empty_window():
    window, next_offset = m._rotate_watchlist_window([], 3)
    assert window == []
    assert next_offset == 3
