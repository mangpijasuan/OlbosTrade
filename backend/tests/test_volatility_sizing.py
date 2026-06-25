"""Tests for volatility-based position sizing (pure, deterministic)."""

from __future__ import annotations

import pytest

from app.services.volatility_sizing import (
    DEFAULT_CONFIG,
    VolSizingConfig,
    describe,
    volatility_scalar,
    vol_adjusted_multiplier,
    _ivr_factor,
    _clamp,
)


def test_clamp():
    assert _clamp(5, 0, 1) == 1
    assert _clamp(-5, 0, 1) == 0
    assert _clamp(0.5, 0, 1) == 0.5


def test_scalar_is_one_at_target_with_mid_ivr():
    # vix == target_vix (18), mid IV rank → ~1.0
    assert volatility_scalar(40.0, 18.0) == pytest.approx(1.0, abs=1e-6)


def test_scalar_shrinks_as_vix_rises():
    calm = volatility_scalar(40.0, 12.0)
    base = volatility_scalar(40.0, 18.0)
    fearful = volatility_scalar(40.0, 35.0)
    assert calm > base > fearful
    assert fearful >= DEFAULT_CONFIG.floor


def test_scalar_capped_in_calm_vol():
    # very low vix would push scalar high, but it is capped
    assert volatility_scalar(40.0, 1.0) == DEFAULT_CONFIG.cap


def test_scalar_floored_in_extreme_vol():
    assert volatility_scalar(40.0, 200.0) == DEFAULT_CONFIG.floor


def test_zero_or_negative_vix_is_neutral():
    assert volatility_scalar(40.0, 0.0) == 1.0
    assert volatility_scalar(40.0, -5.0) == 1.0


def test_ivr_factor_extremes():
    assert _ivr_factor(80.0, DEFAULT_CONFIG) == DEFAULT_CONFIG.high_ivr_factor
    assert _ivr_factor(10.0, DEFAULT_CONFIG) == DEFAULT_CONFIG.low_ivr_factor
    assert _ivr_factor(40.0, DEFAULT_CONFIG) == 1.0


def test_high_ivr_trims_size_vs_mid():
    mid = volatility_scalar(40.0, 18.0)
    high = volatility_scalar(80.0, 18.0)
    assert high < mid


def test_vol_adjusted_multiplier_combines():
    # base 0.75 regime mult at target vix mid ivr → ~0.75
    assert vol_adjusted_multiplier(0.75, 40.0, 18.0) == pytest.approx(0.75, abs=1e-3)
    # negative base clamped to 0
    assert vol_adjusted_multiplier(-1.0, 40.0, 18.0) == 0.0


def test_vol_adjusted_multiplier_scales_down_in_fear():
    calm = vol_adjusted_multiplier(1.0, 40.0, 12.0)
    fearful = vol_adjusted_multiplier(1.0, 40.0, 35.0)
    assert calm > fearful


def test_describe_stances():
    full = describe(40.0, 10.0)       # low vix → capped → full
    assert full["stance"] == "full" and full["scalar"] == DEFAULT_CONFIG.cap
    reduced = describe(40.0, 25.0)
    assert reduced["stance"] == "reduced"
    minimum = describe(40.0, 200.0)
    assert minimum["stance"] == "minimum" and minimum["scalar"] == DEFAULT_CONFIG.floor
    assert "ivr_factor" in full and full["target_vix"] == DEFAULT_CONFIG.target_vix


def test_custom_config_respected():
    cfg = VolSizingConfig(target_vix=20.0, floor=0.5, cap=2.0)
    assert volatility_scalar(40.0, 20.0, cfg) == pytest.approx(1.0, abs=1e-6)
    assert volatility_scalar(40.0, 1.0, cfg) == 2.0
    assert volatility_scalar(40.0, 500.0, cfg) == 0.5
