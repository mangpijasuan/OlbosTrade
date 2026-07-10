"""Unit coverage for the options scan engine's pure decision logic and the
NO-TRADE gate. These lock in the risk-shaping behaviour (entry ladders, skew,
IV rank) and the safety gate before any scan-driven execution is trusted."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.options_scan_engine import (
    _build_entry_ladder,
    _compute_iv_rank,
    _skew_adjustment,
    check_no_trade_gate,
)


# ── _compute_iv_rank ─────────────────────────────────────────────────────────
def test_iv_rank_neutral_when_series_too_short():
    assert _compute_iv_rank([]) == 50.0
    assert _compute_iv_rank([15, 16, 17, 18]) == 50.0  # <5 samples


def test_iv_rank_neutral_when_flat():
    assert _compute_iv_rank([20, 20, 20, 20, 20]) == 50.0


def test_iv_rank_percentile_position():
    # now=20 within [10, 30] → (20-10)/(30-10)*100 = 50
    assert _compute_iv_rank([10, 30, 25, 15, 20]) == 50.0
    # now at the high → 100
    assert _compute_iv_rank([10, 20, 15, 12, 30]) == pytest.approx(100.0)
    # now at the low → 0
    assert _compute_iv_rank([30, 20, 25, 28, 10]) == pytest.approx(0.0)


# ── _skew_adjustment ─────────────────────────────────────────────────────────
def test_skew_neutral_at_iv_rank_50():
    assert _skew_adjustment("put", 0.30, 50) == pytest.approx(0.0)
    assert _skew_adjustment("call", 0.30, 50) == pytest.approx(0.0)


def test_skew_put_gains_with_high_iv_rank():
    # puts gain fear premium as IV rank rises
    assert _skew_adjustment("put", 0.30, 100) == pytest.approx((100 - 50) / 100 * 15)
    assert _skew_adjustment("put", 0.30, 80) > 0


def test_skew_call_gains_with_low_iv_rank():
    # calls benefit from calm/low IV rank
    assert _skew_adjustment("call", 0.30, 0) == pytest.approx((50 - 0) / 100 * 10)
    assert _skew_adjustment("call", 0.30, 20) > 0


# ── _build_entry_ladder (options) ────────────────────────────────────────────
def test_ladder_empty_for_nonpositive_quantity():
    assert _build_entry_ladder(0.1, 0, 100.0) == []
    assert _build_entry_ladder(0.1, -3, 100.0) == []


def test_ladder_full_entry_for_high_confidence_low_kelly():
    ladder = _build_entry_ladder(0.10, 6, 100.0)
    assert len(ladder) == 1
    assert ladder[0].quantity == 6


def test_ladder_two_tranches_for_medium_kelly_sum_to_base():
    ladder = _build_entry_ladder(0.20, 7, 100.0)
    assert len(ladder) == 2
    assert sum(t.quantity for t in ladder) == 7


def test_ladder_three_tranches_for_lower_confidence_sum_to_base():
    ladder = _build_entry_ladder(0.40, 10, 100.0)
    assert len(ladder) == 3
    assert sum(t.quantity for t in ladder) == 10


def test_ladder_caps_thin_edge_to_half_single_tranche():
    # kelly > 50% = edge too thin → one reduced tranche, never full size
    ladder = _build_entry_ladder(0.70, 8, 100.0)
    assert len(ladder) == 1
    assert ladder[0].quantity == 4  # max(1, 8 // 2)
    assert "thin" in ladder[0].entry_note.lower()


def test_ladder_boundaries():
    # exactly 0.50 → not >0.50, is >0.30 → 3 tranches
    assert len(_build_entry_ladder(0.50, 9, 100.0)) == 3
    # exactly 0.15 → not >0.15 → full single entry
    assert len(_build_entry_ladder(0.15, 9, 100.0)) == 1


# ── check_no_trade_gate ──────────────────────────────────────────────────────
async def test_gate_blocks_when_kill_switch_engaged():
    ks = MagicMock()
    ks.is_engaged = True
    ks.status = {"reason": "manual halt"}
    with patch("app.services.kill_switch.kill_switch_service", ks):
        reason = await check_no_trade_gate()
    assert reason is not None
    assert "kill switch" in reason.lower()


async def test_gate_blocks_when_market_closed():
    ks = MagicMock()
    ks.is_engaged = False
    cfg = MagicMock()
    cfg.market_hours_only = True
    with patch("app.services.kill_switch.kill_switch_service", ks), \
         patch("app.core.config.settings", cfg), \
         patch("app.utils.market_hours.market_status",
               return_value={"is_open": False, "reason": "weekend"}):
        reason = await check_no_trade_gate()
    assert reason == "Market closed: weekend"


async def test_gate_allows_when_clear():
    ks = MagicMock()
    ks.is_engaged = False
    cfg = MagicMock()
    cfg.market_hours_only = False
    with patch("app.services.kill_switch.kill_switch_service", ks), \
         patch("app.core.config.settings", cfg):
        assert await check_no_trade_gate() is None
