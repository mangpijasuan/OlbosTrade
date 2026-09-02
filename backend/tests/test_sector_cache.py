"""Tests for ticker -> sector resolution and the Unknown-is-not-a-sector rule.

The bug being pinned: three risk gates treated "Unknown" as a sector and
capped it at 40%. In production that bucket held 94% of the book and produced
179 blocks in 21 days naming GILD, AEP, COST, PDD, SBUX and VRTX as one
concentrated sector.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.services import sector_cache
from app.services.portfolio_engine import (
    UNKNOWN_SECTOR,
    compute_portfolio_risk,
    is_cappable_sector,
    sector_for,
)


@pytest.fixture(autouse=True)
def _reset():
    sector_cache.clear()
    yield
    sector_cache.clear()


# ── The predicate ───────────────────────────────────────────────────────

def test_unknown_is_not_a_cappable_sector():
    assert is_cappable_sector(UNKNOWN_SECTOR) is False
    assert is_cappable_sector(None) is False
    assert is_cappable_sector("") is False


def test_real_sectors_are_cappable():
    for s in ("Technology", "Healthcare", "Utilities", "Index", "Cash"):
        assert is_cappable_sector(s) is True


# ── Resolution ──────────────────────────────────────────────────────────

def test_cache_takes_precedence_over_the_static_map():
    sector_cache._sectors = {"AAPL": "Consumer Cyclical"}
    sector_cache._resolved_at = time.monotonic()
    # Static map says Technology; a real resolution wins.
    assert sector_for("AAPL") == "Consumer Cyclical"


def test_static_map_is_the_fallback_when_the_cache_is_cold():
    assert sector_for("AAPL") == "Technology"
    assert sector_for("SPY") == "Index"


def test_unresolved_ticker_is_unknown():
    assert sector_for("GILD") == UNKNOWN_SECTOR
    assert sector_for("") == UNKNOWN_SECTOR


def test_stale_cache_stops_being_believed():
    sector_cache._sectors = {"GILD": "Healthcare"}
    sector_cache._resolved_at = time.monotonic() - sector_cache.STALE_AFTER_S - 1
    assert sector_cache.sector_for_cached("GILD") is None
    assert sector_for("GILD") == UNKNOWN_SECTOR


def test_lookup_is_case_insensitive():
    sector_cache._sectors = {"GILD": "Healthcare"}
    sector_cache._resolved_at = time.monotonic()
    assert sector_for("gild") == "Healthcare"


# ── Vocabulary ──────────────────────────────────────────────────────────

def test_provider_labels_normalise_into_one_vocabulary():
    assert sector_cache.canonical_sector("Communication Services") == "Communication Services"
    assert sector_cache.canonical_sector("  technology  ") == "Technology"
    assert sector_cache.canonical_sector("Financial Services") == "Financial Services"


def test_unrecognised_provider_label_is_not_invented():
    assert sector_cache.canonical_sector("Conglomerates") is None
    assert sector_cache.canonical_sector(None) is None
    assert sector_cache.canonical_sector("") is None


def test_static_map_uses_the_same_vocabulary_as_the_cache():
    """A company reaching a different bucket depending on cache warmth would
    split a sector in two and understate concentration."""
    from app.services.portfolio_engine import SECTORS
    etf_pseudo_sectors = {"Index", "Bonds", "Commodity", "Dollar", "Cash"}
    for ticker, sector in SECTORS.items():
        if sector in etf_pseudo_sectors:
            continue
        assert sector_cache.canonical_sector(sector) == sector, (
            f"{ticker} -> {sector!r} is not in the canonical vocabulary")


# ── The gate behaviour this all exists for ──────────────────────────────

def test_unknown_bucket_never_raises_a_concentration_flag():
    """The production shape: three unclassified names, 94% of the book."""
    positions = [
        {"underlying": "GILD", "risk_dollars": 60_000, "sector": UNKNOWN_SECTOR},
        {"underlying": "AEP", "risk_dollars": 20_000, "sector": UNKNOWN_SECTOR},
        {"underlying": "COST", "risk_dollars": 14_000, "sector": UNKNOWN_SECTOR},
    ]
    r = compute_portfolio_risk(positions, 100_000.0)
    assert not any("sector_concentration" in f for f in r["concentration_flags"])
    assert r["largest_sector"] is None
    assert r["sector_classified_pct"] == 0.0
    assert r["unclassified_sector_dollars"] == 94_000.0


def test_a_real_sector_still_breaches_its_cap():
    positions = [
        {"underlying": "NVDA", "risk_dollars": 30_000, "sector": "Technology"},
        {"underlying": "AMD", "risk_dollars": 20_000, "sector": "Technology"},
    ]
    r = compute_portfolio_risk(positions, 100_000.0)
    assert any("sector_concentration:Technology" in f
               for f in r["concentration_flags"])
    assert r["sector_classified_pct"] == 100.0


def test_unknown_does_not_mask_a_real_sector_breach():
    """Unknown holds the most dollars, but Technology is what gets flagged —
    the cap must still see the bucket it can actually reason about."""
    positions = [
        {"underlying": "GILD", "risk_dollars": 50_000, "sector": UNKNOWN_SECTOR},
        {"underlying": "NVDA", "risk_dollars": 45_000, "sector": "Technology"},
    ]
    r = compute_portfolio_risk(positions, 100_000.0)
    assert r["largest_sector"] == "Technology"
    assert any("sector_concentration:Technology" in f
               for f in r["concentration_flags"])
    assert r["sector_classified_pct"] == pytest.approx(47.37, abs=0.01)


def test_unclassified_exposure_is_still_reported():
    positions = [{"underlying": "GILD", "risk_dollars": 40_000,
                  "sector": UNKNOWN_SECTOR}]
    r = compute_portfolio_risk(positions, 100_000.0)
    assert r["exposure_by_sector"][UNKNOWN_SECTOR] == 40_000.0


# ── Refresh ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_populates_only_what_resolves():
    def fake(ticker):
        return {"GILD": "Healthcare", "AEP": "Utilities"}.get(ticker)

    with patch.object(sector_cache, "_fetch_one", side_effect=fake):
        out = await sector_cache.refresh(["GILD", "AEP", "CRWV"])

    assert out["resolved"] == 2
    assert out["unresolved"] == 1
    assert sector_for("GILD") == "Healthcare"
    assert sector_for("CRWV") == UNKNOWN_SECTOR


@pytest.mark.asyncio
async def test_a_failed_fetch_does_not_downgrade_a_known_ticker():
    with patch.object(sector_cache, "_fetch_one", side_effect=lambda t: "Healthcare"):
        await sector_cache.refresh(["GILD"])
    with patch.object(sector_cache, "_fetch_one", side_effect=lambda t: None):
        await sector_cache.refresh(["GILD"])
    assert sector_for("GILD") == "Healthcare"


@pytest.mark.asyncio
async def test_a_raising_fetch_does_not_break_the_whole_refresh():
    def fake(ticker):
        if ticker == "BOOM":
            raise RuntimeError("provider exploded")
        return "Healthcare"

    with patch.object(sector_cache, "_fetch_one", side_effect=fake):
        out = await sector_cache.refresh(["GILD", "BOOM"])
    assert sector_for("GILD") == "Healthcare"
    assert out["unresolved"] == 1
