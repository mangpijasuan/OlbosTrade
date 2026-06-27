"""Tests for the margin monitor (utilization / buying-power-reduction status)."""

from __future__ import annotations

from app.services.margin_monitor import evaluate_margin


def test_ok_low_utilization():
    s = evaluate_margin(net_liquidation=100_000, maintenance_margin=10_000,
                        excess_liquidity=90_000, buying_power=200_000)
    assert s.status == "ok" and s.utilization_pct == 10.0
    assert "nominal" in s.detail


def test_warn_band():
    s = evaluate_margin(net_liquidation=100_000, maintenance_margin=60_000,
                        excess_liquidity=40_000)
    assert s.status == "warn" and s.utilization_pct == 60.0


def test_critical_high_utilization():
    s = evaluate_margin(net_liquidation=100_000, maintenance_margin=85_000,
                        excess_liquidity=15_000)
    assert s.status == "critical" and s.utilization_pct == 85.0


def test_critical_when_excess_liquidity_exhausted():
    """Even at modest utilization, non-positive excess liquidity is critical."""
    s = evaluate_margin(net_liquidation=100_000, maintenance_margin=30_000,
                        excess_liquidity=0)
    assert s.status == "critical" and "Excess liquidity" in s.detail


def test_zero_net_liq_with_margin_is_full_utilization():
    s = evaluate_margin(net_liquidation=0, maintenance_margin=5_000,
                        excess_liquidity=-1)
    assert s.utilization_pct == 100.0 and s.status == "critical"


def test_zero_everything_is_ok():
    s = evaluate_margin(net_liquidation=0, maintenance_margin=0, excess_liquidity=0)
    assert s.status == "ok" and s.utilization_pct == 0.0


def test_custom_thresholds():
    s = evaluate_margin(net_liquidation=100_000, maintenance_margin=35_000,
                        excess_liquidity=65_000, warn_pct=0.30, critical_pct=0.50)
    assert s.status == "warn"   # 35% ≥ 30% warn, < 50% critical


def test_to_dict_roundtrip():
    d = evaluate_margin(net_liquidation=100_000, maintenance_margin=10_000,
                        excess_liquidity=90_000, buying_power=5, init_margin=12_000).to_dict()
    assert d["status"] == "ok" and d["init_margin"] == 12_000.0 and d["buying_power"] == 5.0
