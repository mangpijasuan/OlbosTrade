"""Tests for the Alpha Edge Signal scoring engine (deterministic pure
functions, no network/DB — see app/services/alpha_edge_engine.py for the
design rationale)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from types import SimpleNamespace

from app.services.alpha_edge_engine import (
    CONFIRMED,
    DECAYING,
    EXPIRED,
    NEW,
    compute_equity_scores,
    compute_options_exit_score,
    compute_options_hold_score,
    equity_lifecycle_state,
    equity_score_trend,
    options_lifecycle_state,
    split_evidence,
)


# ── compute_equity_scores ───────────────────────────────────────────────────

def test_entry_score_always_computed_no_position():
    entry, hold, exit_ = compute_equity_scores("BUY", 0.8, None)
    assert entry == 80
    assert hold is None and exit_ is None


def test_hold_score_aligned_position_scores_high():
    entry, hold, exit_ = compute_equity_scores("BUY", 0.8, "BUY")
    assert hold == 90  # 50 + 1*0.8*50
    assert exit_ == 10  # complement


def test_hold_score_reversed_position_scores_low():
    entry, hold, exit_ = compute_equity_scores("SELL", 0.8, "BUY")
    assert hold == 10
    assert exit_ == 90


def test_hold_score_neutral_hold_centers_at_50():
    entry, hold, exit_ = compute_equity_scores("HOLD", 0.5, "BUY")
    assert hold == 50 and exit_ == 50


def test_scores_clamped_0_100():
    entry, hold, exit_ = compute_equity_scores("BUY", 1.0, "BUY")
    assert 0 <= hold <= 100 and 0 <= exit_ <= 100


# ── equity_lifecycle_state ──────────────────────────────────────────────────

def test_lifecycle_new_no_position_no_anchor():
    assert equity_lifecycle_state(None, "BUY", None) == NEW


def test_lifecycle_confirmed_aligned():
    assert equity_lifecycle_state("BUY", "BUY", "pending") == CONFIRMED


def test_lifecycle_decaying_on_hold():
    assert equity_lifecycle_state("BUY", "HOLD", "pending") == DECAYING


def test_lifecycle_expired_on_reversal():
    assert equity_lifecycle_state("BUY", "SELL", "pending") == EXPIRED


def test_lifecycle_expired_on_terminal_outcome():
    assert equity_lifecycle_state(None, "BUY", "target_hit") == EXPIRED
    assert equity_lifecycle_state(None, "BUY", "stop_hit") == EXPIRED
    assert equity_lifecycle_state(None, "BUY", "expired") == EXPIRED


def test_lifecycle_never_expired_for_pending_alone():
    """A merely-pending anchor with no position must not read as expired —
    only a genuinely terminal outcome or a reversed position does."""
    assert equity_lifecycle_state(None, "BUY", "pending") != EXPIRED


# ── equity_score_trend ──────────────────────────────────────────────────────

def test_trend_not_tracked_without_anchor():
    t = equity_score_trend(80, None, None)
    assert t.direction == "not_tracked" and t.delta is None


def test_trend_improving():
    t = equity_score_trend(80, 0.60, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert t.direction == "improving" and t.delta == 20.0


def test_trend_declining():
    t = equity_score_trend(30, 0.60, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert t.direction == "declining" and t.delta == -30.0


def test_trend_flat_within_band():
    t = equity_score_trend(62, 0.60, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert t.direction == "flat"


# ── compute_options_exit_score ──────────────────────────────────────────────

def test_options_exit_score_zero_when_no_adverse_excursion():
    assert compute_options_exit_score(450, 445, 1.5, 0.0) == 0
    assert compute_options_exit_score(450, 445, 1.5, None) == 0


def test_options_exit_score_scales_with_mae():
    # max_loss = (450-445)*100 - 1.5*100 = 350
    assert compute_options_exit_score(450, 445, 1.5, -175.0) == 50
    assert compute_options_exit_score(450, 445, 1.5, -350.0) == 100


def test_options_exit_score_clamped_at_100_beyond_max_loss():
    assert compute_options_exit_score(450, 445, 1.5, -1000.0) == 100


def test_options_exit_score_zero_when_max_loss_non_positive():
    # credit >= width*100 → non-positive theoretical max loss
    assert compute_options_exit_score(450, 445, 10.0, -50.0) == 0


# ── compute_options_hold_score ───────────────────────────────────────────────

def _opt_trade(short=450, long=445, credit=1.5, mae=None):
    return SimpleNamespace(short_strike=short, long_strike=long,
                            credit_received=credit, mae_pnl=mae)


def test_hold_score_options_no_mae_defaults_to_full_hold():
    assert compute_options_hold_score(_opt_trade(mae=None)) == 100


def test_hold_score_options_no_adverse_excursion():
    assert compute_options_hold_score(_opt_trade(mae=0.0)) == 100


def test_hold_score_options_scales_inversely_with_mae():
    # max_loss = (450-445)*100 - 1.5*100 = 350; exit=50 at mae=-175 -> hold=50
    assert compute_options_hold_score(_opt_trade(mae=-175.0)) == 50
    # exit=100 at mae=-350 -> hold=0
    assert compute_options_hold_score(_opt_trade(mae=-350.0)) == 0


# ── options_lifecycle_state ──────────────────────────────────────────────────

def test_options_lifecycle_new_without_trade():
    assert options_lifecycle_state(None, None) == NEW


def test_options_lifecycle_confirmed_low_exit_pressure():
    assert options_lifecycle_state("open", 30) == CONFIRMED


def test_options_lifecycle_decaying_high_exit_pressure():
    assert options_lifecycle_state("open", 60) == DECAYING


def test_options_lifecycle_expired_closed_trade():
    assert options_lifecycle_state("closed", 10) == EXPIRED
    assert options_lifecycle_state("expired", 90) == EXPIRED


# ── split_evidence ───────────────────────────────────────────────────────────

def test_split_evidence_sorts_and_caps_top_3():
    reasons = {"a": 2.0, "b": -1.5, "c": 0.8, "d": -3.0, "e": 1.2, "f": -0.5}
    pos, neg = split_evidence(reasons, top_n=3)
    assert [p["feature"] for p in pos] == ["a", "e", "c"]
    assert [n["feature"] for n in neg] == ["d", "b", "f"]


def test_split_evidence_empty_reasons():
    pos, neg = split_evidence({})
    assert pos == [] and neg == []


def test_split_evidence_all_positive_no_negative():
    pos, neg = split_evidence({"a": 1.0, "b": 2.0})
    assert len(pos) == 2 and neg == []
