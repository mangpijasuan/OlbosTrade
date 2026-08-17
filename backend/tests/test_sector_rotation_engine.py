"""Tests for the Sector Rotation ranking engine (deterministic pure functions
plus the async orchestrator with mocked fetches — no network/DB — see
app/services/sector_rotation_engine.py for the design rationale)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.sector_rotation_engine import (
    SECTOR_ETFS,
    TIMEFRAMES,
    compute_returns,
    get_sector_rotation,
    rank_sectors,
)


# ── compute_returns ──────────────────────────────────────────────────────

def test_compute_returns_full_history():
    # 70 closes; set the exact indices compute_returns reads from (closes[-1-offset])
    # for each timeframe, leave the rest as a non-zero filler.
    closes = [50.0] * 70
    closes[-1] = 110.0
    closes[-1 - 1] = 109.0   # 1D base
    closes[-1 - 5] = 105.0   # 1W base
    closes[-1 - 21] = 100.0  # 1M base
    closes[-1 - 63] = 90.0   # 3M base
    out = compute_returns(closes)
    assert set(out.keys()) == set(TIMEFRAMES.keys())
    assert out["1D"] == pytest.approx((110.0 - 109.0) / 109.0)
    assert out["1W"] == pytest.approx((110.0 - 105.0) / 105.0)
    assert out["1M"] == pytest.approx((110.0 - 100.0) / 100.0)
    assert out["3M"] == pytest.approx((110.0 - 90.0) / 90.0)


def test_compute_returns_insufficient_history_returns_none_not_zero():
    closes = [100.0, 101.0, 102.0]  # only 3 bars — nowhere near 1M(21) or 3M(63)
    out = compute_returns(closes)
    assert out["1D"] is not None
    assert out["1M"] is None
    assert out["3M"] is None


def test_compute_returns_empty_list():
    out = compute_returns([])
    assert all(v is None for v in out.values())


def test_compute_returns_guards_zero_division():
    closes = [0.0, 0.0, 10.0]
    out = compute_returns(closes)
    assert out["1D"] is None  # base close is 0 — skipped, not a divide-by-zero crash


# ── rank_sectors ──────────────────────────────────────────────────────────

def test_rank_sectors_orders_descending_by_basis():
    returns = {
        "XLK": {"1M": 0.10},
        "XLF": {"1M": 0.05},
        "XLE": {"1M": 0.20},
    }
    ranks = rank_sectors(returns, "1M")
    assert ranks["XLE"] == 1
    assert ranks["XLK"] == 2
    assert ranks["XLF"] == 3


def test_rank_sectors_excludes_missing_timeframe():
    returns = {
        "XLK": {"1M": 0.10},
        "XLF": {"1M": None},
    }
    ranks = rank_sectors(returns, "1M")
    assert ranks["XLK"] == 1
    assert ranks["XLF"] is None


def test_rank_sectors_empty_input():
    assert rank_sectors({}, "1M") == {}


# ── get_sector_rotation (orchestrator, mocked fetch) ───────────────────────

def _closes_with_return(base: float, pct_1m: float, n: int = 70) -> list[float]:
    """Build a closes series where the 1M (21-bar) return is exactly pct_1m."""
    closes = [base] * (n - 21) + [base * (1 + pct_1m)] * 22
    return closes


async def test_get_sector_rotation_ranks_all_successful_fetches():
    async def fake_fetch(ticker: str) -> list[float]:
        pct = {"XLK": 0.10, "XLF": 0.02}.get(ticker, 0.05)
        return _closes_with_return(100.0, pct)

    with patch("app.services.sector_rotation_engine._fetch_closes", side_effect=fake_fetch):
        result = await get_sector_rotation()

    assert result["rank_basis"] == "1M"
    assert len(result["sectors"]) == len(SECTOR_ETFS)
    assert result["excluded"] == []
    xlk = next(s for s in result["sectors"] if s["ticker"] == "XLK")
    xlf = next(s for s in result["sectors"] if s["ticker"] == "XLF")
    assert xlk["rank"] < xlf["rank"]  # XLK's higher 1M return ranks better


async def test_get_sector_rotation_excludes_failed_fetch_without_breaking_others():
    async def fake_fetch(ticker: str) -> list[float]:
        if ticker == "XLRE":
            return []  # simulated fetch failure
        return _closes_with_return(100.0, 0.05)

    with patch("app.services.sector_rotation_engine._fetch_closes", side_effect=fake_fetch):
        result = await get_sector_rotation()

    assert len(result["sectors"]) == len(SECTOR_ETFS) - 1
    assert result["excluded"] == [{"ticker": "XLRE", "name": "Real Estate", "reason": "no data returned"}]
    assert all(s["ticker"] != "XLRE" for s in result["sectors"])


async def test_get_sector_rotation_rank_change_reflects_movement():
    # XLK starts flat, ends strongly up in the last 5 bars -> should show a
    # positive rank_change (moved up in the ranking vs 5 trading days ago).
    async def fake_fetch(ticker: str) -> list[float]:
        if ticker == "XLK":
            closes = _closes_with_return(100.0, 0.01)
            closes[-5:] = [c * 1.15 for c in closes[-5:]]
            return closes
        return _closes_with_return(100.0, 0.03)

    with patch("app.services.sector_rotation_engine._fetch_closes", side_effect=fake_fetch):
        result = await get_sector_rotation()

    xlk = next(s for s in result["sectors"] if s["ticker"] == "XLK")
    assert xlk["rank_change"] is not None
    assert xlk["rank_change"] > 0


async def test_get_sector_rotation_all_fetches_fail_returns_empty_not_crash():
    async def fake_fetch(ticker: str) -> list[float]:
        return []

    with patch("app.services.sector_rotation_engine._fetch_closes", side_effect=fake_fetch):
        result = await get_sector_rotation()

    assert result["sectors"] == []
    assert len(result["excluded"]) == len(SECTOR_ETFS)
