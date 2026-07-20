"""Unit coverage for the equity scan engine's pure math: probability-of-profit,
Kelly sizing, and the entry ladder."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from app.services.equity_scan_engine import (
    EquityScanCandidate,
    _build_entry_ladder,
    _compute_iv_rank_for_ticker,
    _compute_kelly_fraction,
    _compute_pop_from_distance,
    _yf_bars_for_ticker,
    scan_options_for_ticker,
)


# ── Bar depth (ARCHITECTURE_AUDIT.md finding #4) ─────────────────────────────
def test_default_bar_limit_is_250_not_120():
    # With 120 bars EMA200 is always NaN, forcing above_ema200=False and
    # skewing every signal ~1pt bearish vs. the background scanner's own
    # 250-bar fetch (main.py's _run_equity_scan). Both must match.
    assert inspect.signature(_yf_bars_for_ticker).parameters["limit"].default == 250


@pytest.mark.asyncio
async def test_scan_options_for_ticker_fetches_250_bars():
    with patch("app.services.equity_scan_engine._yf_bars_for_ticker",
               new=AsyncMock(return_value=[])) as bars_mock, \
         patch("app.services.equity_scan_engine.earnings_gate", return_value=False):
        await scan_options_for_ticker("AAPL")
    bars_mock.assert_awaited_once_with("AAPL", limit=250)


# ── Signal attribution (ARCHITECTURE_AUDIT.md finding #4) ────────────────────
def test_candidate_default_source_is_equity_scan_engine():
    candidate = EquityScanCandidate(
        ticker="AAPL", action="BUY", confidence=0.6, expected_value=10.0,
        ev_per_risk=0.5, pop=0.6, kelly_fraction=0.1, entry_price=100.0,
        stop_price=95.0, target_price=110.0, max_loss=5.0, max_profit=10.0,
    )
    assert candidate.source == "Equity Scan Engine"
    assert candidate.as_dict()["source"] == "Equity Scan Engine"


# ── _compute_iv_rank_for_ticker (equity_scan_engine.py:449 TypeError) ────────
# get_iv_signal_boost returns {"iv_rank": None, ...} whenever options aren't
# supported or the IV surface builder isn't wired in (always true today — no
# caller passes one) — sum(all_iv_rank) in scan_options crashed on that None.
@pytest.mark.asyncio
async def test_iv_rank_none_from_boost_normalizes_to_zero():
    with patch(
        "app.services.equity_scan_engine.get_iv_signal_boost",
        new=AsyncMock(return_value={"iv_rank": None, "boost": 0.0}),
    ):
        iv_rank, realized_vol = await _compute_iv_rank_for_ticker("AAPL", broker=object())
    assert iv_rank == 0.0
    assert realized_vol == 0.0
    assert isinstance(iv_rank, float) and isinstance(realized_vol, float)


@pytest.mark.asyncio
async def test_iv_rank_real_value_passes_through():
    with patch(
        "app.services.equity_scan_engine.get_iv_signal_boost",
        new=AsyncMock(return_value={"iv_rank": 42.5, "realized_vol": 0.18}),
    ):
        iv_rank, realized_vol = await _compute_iv_rank_for_ticker("AAPL", broker=object())
    assert iv_rank == 42.5
    assert realized_vol == 0.18


# ── _compute_pop_from_distance ───────────────────────────────────────────────
def test_pop_neutral_without_volatility():
    assert _compute_pop_from_distance(100, 110, 95, 0) == 0.5
    assert _compute_pop_from_distance(0, 110, 95, 2) == 0.5


def test_pop_equidistant_target_and_stop_is_even():
    # target +5, stop -5 → 50/50
    assert _compute_pop_from_distance(100, 105, 95, 2) == pytest.approx(0.5)


def test_pop_higher_when_stop_has_more_room_than_target():
    # POP = dist_to_stop / (dist_to_target + dist_to_stop): a wider stop (more
    # room before stopping out) raises the probability of reaching target first.
    pop = _compute_pop_from_distance(100, 110, 85, 2)  # target 10 away, stop 15 away
    assert pop > 0.5
    # and a tight stop (easily hit) lowers it
    assert _compute_pop_from_distance(100, 110, 98, 2) < 0.5


def test_pop_clamped_to_bounds():
    val = _compute_pop_from_distance(100, 100.0001, 1, 2)  # tiny target dist
    assert 0.01 <= val <= 0.99


# ── _compute_kelly_fraction ──────────────────────────────────────────────────
def test_kelly_floor_when_no_edge_inputs():
    assert _compute_kelly_fraction(0.6, 0, 100) == 0.05
    assert _compute_kelly_fraction(0.6, 100, 0) == 0.05


def test_kelly_clamped_to_50_percent_ceiling():
    # very favourable odds should still cap at 0.50
    assert _compute_kelly_fraction(0.95, 500, 100) == 0.50


def test_kelly_positive_edge_between_bounds():
    k = _compute_kelly_fraction(0.6, 150, 100)
    assert 0.01 <= k <= 0.50


def test_kelly_floor_on_negative_edge():
    # coin-flip odds with symmetric payoff → no edge → floored, never negative
    k = _compute_kelly_fraction(0.4, 100, 100)
    assert k == 0.01


# ── _build_entry_ladder (equity) ─────────────────────────────────────────────
def test_equity_ladder_full_entry_low_kelly():
    ladder = _build_entry_ladder(0.10, 50.0, 45.0, 60.0)
    assert len(ladder) == 1
    assert ladder[0]["pct_position"] == 100


def test_equity_ladder_two_tranches_medium_kelly():
    ladder = _build_entry_ladder(0.20, 50.0, 45.0, 60.0)
    assert len(ladder) == 2
    assert sum(t["pct_position"] for t in ladder) == 100


def test_equity_ladder_three_tranches_high_kelly():
    ladder = _build_entry_ladder(0.40, 50.0, 45.0, 60.0)
    assert len(ladder) == 3
    assert sum(t["pct_position"] for t in ladder) == 100
    # later tranches scale in on weakness (lower price)
    assert ladder[1]["entry_price"] < ladder[0]["entry_price"]
