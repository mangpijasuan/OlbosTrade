"""
Unit tests for the options-chain TTL cache — the LIVE/DEGRADED/STALE
data_status contract must never present stale data as live.

Run with: pytest tests/test_options_chain_cache.py -v
"""

import asyncio

import pytest

from app.services import options_chain_cache


@pytest.fixture(autouse=True)
def _reset_cache():
    options_chain_cache.clear()
    yield
    options_chain_cache.clear()


@pytest.mark.asyncio
async def test_fresh_fetch_is_live():
    async def fetch():
        return {"symbol": "SPY"}

    chain, status = await options_chain_cache.get_chain("SPY", "2026-09-18", fetch)
    assert status == "LIVE"
    assert chain == {"symbol": "SPY"}


@pytest.mark.asyncio
async def test_second_fetch_within_ttl_is_degraded_and_does_not_refetch():
    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return {"symbol": "SPY", "n": call_count}

    first, first_status = await options_chain_cache.get_chain("SPY", "2026-09-18", fetch)
    second, second_status = await options_chain_cache.get_chain("SPY", "2026-09-18", fetch)

    assert first_status == "LIVE"
    assert second_status == "DEGRADED"
    assert second == first  # same cached payload, not a fresh call
    assert call_count == 1


@pytest.mark.asyncio
async def test_expired_entry_triggers_a_fresh_fetch(monkeypatch):
    monkeypatch.setattr(options_chain_cache, "TTL_SECONDS", 0.02)
    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return {"n": call_count}

    await options_chain_cache.get_chain("SPY", "2026-09-18", fetch)
    await asyncio.sleep(0.05)
    chain, status = await options_chain_cache.get_chain("SPY", "2026-09-18", fetch)

    assert status == "LIVE"
    assert call_count == 2
    assert chain == {"n": 2}


@pytest.mark.asyncio
async def test_failed_refetch_falls_back_to_stale_cache_not_live(monkeypatch):
    monkeypatch.setattr(options_chain_cache, "TTL_SECONDS", 0.02)

    async def good_fetch():
        return {"n": 1}

    async def bad_fetch():
        raise ConnectionError("IBKR unreachable")

    await options_chain_cache.get_chain("SPY", "2026-09-18", good_fetch)
    await asyncio.sleep(0.05)  # let the entry expire
    chain, status = await options_chain_cache.get_chain("SPY", "2026-09-18", bad_fetch)

    assert status == "STALE"
    assert chain == {"n": 1}  # the old data, never mislabeled as LIVE


@pytest.mark.asyncio
async def test_failed_fetch_with_no_cache_raises():
    async def bad_fetch():
        raise ConnectionError("IBKR unreachable")

    with pytest.raises(ConnectionError):
        await options_chain_cache.get_chain("NEWSYM", "2026-09-18", bad_fetch)


@pytest.mark.asyncio
async def test_different_expiries_are_cached_independently():
    async def fetch_a():
        return {"expiry": "A"}

    async def fetch_b():
        return {"expiry": "B"}

    chain_a, _ = await options_chain_cache.get_chain("SPY", "2026-09-18", fetch_a)
    chain_b, _ = await options_chain_cache.get_chain("SPY", "2026-10-16", fetch_b)

    assert chain_a == {"expiry": "A"}
    assert chain_b == {"expiry": "B"}


def test_stats_reports_hit_rate():
    options_chain_cache._hits = 3
    options_chain_cache._misses = 1
    stats = options_chain_cache.stats()
    assert stats["hits"] == 3
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.75
