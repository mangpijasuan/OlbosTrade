"""
GET /api/equity/signals must dedupe by ticker before slicing/counting.

_recent_signals holds one raw entry per ticker PER SCAN CYCLE (newest
inserted at index 0), so once more than one scan cycle has run, the same
ticker appears multiple times with different ids. Undeduped, this rendered
as duplicate cards in the frontend and inflated the "total"/"actionable"
counts (user report: "some are duplicated"). Confirmed real by direct
observation on the live page ("150 total" for a 102-ticker watchlist).
"""

from __future__ import annotations

import pytest

from app.api.routes import equity


def _sig(ticker: str, sig_id: str, action: str = "BUY") -> dict:
    return {"id": sig_id, "ticker": ticker, "action": action, "confidence": 0.7}


@pytest.fixture(autouse=True)
def _reset_recent_signals():
    original = list(equity._recent_signals)
    equity._recent_signals.clear()
    yield
    equity._recent_signals.clear()
    equity._recent_signals.extend(original)


@pytest.mark.asyncio
async def test_dedupes_repeated_ticker_across_scan_cycles():
    # Newest-first insertion order, as main.py's _recent_signals.insert(0, ...) produces.
    equity._recent_signals.extend([
        _sig("AAPL", "cycle2-aapl"),   # newest AAPL entry (most recent scan cycle)
        _sig("MSFT", "cycle2-msft"),
        _sig("AAPL", "cycle1-aapl"),   # older AAPL entry from a prior cycle
        _sig("MSFT", "cycle1-msft"),
    ])

    out = await equity.list_equity_signals()

    tickers = [s["ticker"] for s in out["signals"]]
    assert tickers.count("AAPL") == 1
    assert tickers.count("MSFT") == 1
    assert out["total"] == 2


@pytest.mark.asyncio
async def test_keeps_the_most_recent_entry_per_ticker():
    equity._recent_signals.extend([
        _sig("AAPL", "newest", action="SELL"),
        _sig("AAPL", "oldest", action="BUY"),
    ])

    out = await equity.list_equity_signals()

    assert len(out["signals"]) == 1
    assert out["signals"][0]["id"] == "newest"
    assert out["signals"][0]["action"] == "SELL"


@pytest.mark.asyncio
async def test_no_duplicates_is_a_no_op():
    equity._recent_signals.extend([_sig("AAPL", "a1"), _sig("MSFT", "m1"), _sig("NVDA", "n1")])

    out = await equity.list_equity_signals()

    assert out["total"] == 3
    assert [s["id"] for s in out["signals"]] == ["a1", "m1", "n1"]


@pytest.mark.asyncio
async def test_limit_applies_after_dedup_not_before():
    # 2 unique tickers each appearing twice (4 raw entries) — a pre-dedup
    # limit of 3 would have wrongly dropped one ticker entirely.
    equity._recent_signals.extend([
        _sig("AAPL", "a-new"), _sig("MSFT", "m-new"),
        _sig("AAPL", "a-old"), _sig("MSFT", "m-old"),
    ])

    out = await equity.list_equity_signals(limit=3)

    tickers = {s["ticker"] for s in out["signals"]}
    assert tickers == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_empty_store_returns_empty():
    out = await equity.list_equity_signals()
    assert out == {"signals": [], "total": 0}
