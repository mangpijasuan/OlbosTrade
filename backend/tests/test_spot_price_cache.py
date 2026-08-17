"""
Unit tests for the spot-price TTL cache — the LIVE/DEGRADED/STALE
data_status contract must never present stale data as live.
"""

import asyncio

import pytest

from app.services import spot_price_cache


@pytest.fixture(autouse=True)
def _reset_cache():
    spot_price_cache.clear()
    yield
    spot_price_cache.clear()


@pytest.mark.asyncio
async def test_fresh_fetch_is_live():
    async def fetch():
        return 452.31

    spot, status = await spot_price_cache.get_spot("SPY", fetch)
    assert status == "LIVE"
    assert spot == 452.31


@pytest.mark.asyncio
async def test_second_fetch_within_ttl_is_degraded_and_does_not_refetch():
    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return 450.0 + call_count

    first, first_status = await spot_price_cache.get_spot("SPY", fetch)
    second, second_status = await spot_price_cache.get_spot("SPY", fetch)

    assert first_status == "LIVE"
    assert second_status == "DEGRADED"
    assert second == first
    assert call_count == 1


@pytest.mark.asyncio
async def test_expired_entry_triggers_a_fresh_fetch(monkeypatch):
    monkeypatch.setattr(spot_price_cache, "TTL_SECONDS", 0.02)
    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return float(call_count)

    await spot_price_cache.get_spot("SPY", fetch)
    await asyncio.sleep(0.05)
    spot, status = await spot_price_cache.get_spot("SPY", fetch)

    assert status == "LIVE"
    assert call_count == 2
    assert spot == 2.0


@pytest.mark.asyncio
async def test_failed_refetch_falls_back_to_stale_cache_not_live(monkeypatch):
    monkeypatch.setattr(spot_price_cache, "TTL_SECONDS", 0.02)

    async def good_fetch():
        return 452.31

    async def bad_fetch():
        raise ConnectionError("yfinance unreachable")

    await spot_price_cache.get_spot("SPY", good_fetch)
    await asyncio.sleep(0.05)  # let the entry expire
    spot, status = await spot_price_cache.get_spot("SPY", bad_fetch)

    assert status == "STALE"
    assert spot == 452.31  # the old price, never mislabeled as LIVE


@pytest.mark.asyncio
async def test_failed_fetch_with_no_cache_raises():
    async def bad_fetch():
        raise ConnectionError("yfinance unreachable")

    with pytest.raises(ConnectionError):
        await spot_price_cache.get_spot("NEWSYM", bad_fetch)


@pytest.mark.asyncio
async def test_different_symbols_are_cached_independently():
    async def fetch_spy():
        return 452.31

    async def fetch_aapl():
        return 231.5

    spy, _ = await spot_price_cache.get_spot("SPY", fetch_spy)
    aapl, _ = await spot_price_cache.get_spot("AAPL", fetch_aapl)

    assert spy == 452.31
    assert aapl == 231.5


@pytest.mark.asyncio
async def test_symbol_lookup_is_case_insensitive():
    async def fetch():
        return 452.31

    await spot_price_cache.get_spot("spy", fetch)
    _, status = await spot_price_cache.get_spot("SPY", fetch)
    assert status == "DEGRADED"


def test_stats_reports_hit_rate():
    spot_price_cache._hits = 3
    spot_price_cache._misses = 1
    stats = spot_price_cache.stats()
    assert stats["hits"] == 3
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.75
