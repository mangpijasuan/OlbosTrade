"""The scan must be bounded: capped fan-out, and no single ticker able to
hold it open.

Before this, ~100 tickers fired at once with no cap and no per-ticker
deadline. A manual scan on 2026-08-30 ran past 130s and nginx returned 504
while the work carried on invisibly behind it.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import equity_scan_engine as eng


@pytest.mark.asyncio
async def test_fan_out_is_capped(monkeypatch):
    live = 0
    peak = 0

    async def fake(ticker, broker):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return None

    monkeypatch.setattr(eng, "scan_options_for_ticker", fake)
    await eng.scan_options(tickers=[f"T{i}" for i in range(40)], limit=5)
    assert peak <= eng.SCAN_CONCURRENCY, f"fan-out reached {peak}"


@pytest.mark.asyncio
async def test_a_hung_ticker_cannot_hold_the_scan_open(monkeypatch):
    async def fake(ticker, broker):
        if ticker == "HUNG":
            await asyncio.sleep(3600)     # never answers
        return None

    monkeypatch.setattr(eng, "scan_options_for_ticker", fake)
    monkeypatch.setattr(eng, "SCAN_TICKER_TIMEOUT_S", 0.05)

    res = await asyncio.wait_for(
        eng.scan_options(tickers=["AAA", "HUNG", "BBB"], limit=5), timeout=5,
    )
    # The scan returns rather than hanging; the hung symbol simply is not in it.
    assert res.tickers_scanned == ["AAA", "HUNG", "BBB"]


@pytest.mark.asyncio
async def test_one_failing_ticker_does_not_void_the_others(monkeypatch):
    async def fake(ticker, broker):
        if ticker == "BOOM":
            raise RuntimeError("provider exploded")
        return None

    monkeypatch.setattr(eng, "scan_options_for_ticker", fake)
    res = await eng.scan_options(tickers=["AAA", "BOOM", "CCC"], limit=5)
    assert res.error == ""
