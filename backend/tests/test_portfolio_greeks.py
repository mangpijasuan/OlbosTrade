"""Tests for PortfolioGreeksTracker — net delta/vega/theta aggregation."""

from __future__ import annotations

from app.services.portfolio_greeks import PortfolioGreeksTracker


def _tracker():
    t = PortfolioGreeksTracker()
    # equity 100 shares long → delta 100 (normalised /100 = 1.0 options-equivalent)
    t.add_equity_position("AAPL", 100, "long")
    # short 2 option contracts, delta -0.3 each → -0.6 delta, 0.2 vega, 0.1 theta
    t.add_options_position("SPY", delta=-0.3, vega=0.1, theta=0.05, qty=2, side="short")
    return t


def test_net_greeks():
    t = _tracker()
    assert abs(t.net_delta() - 0.4) < 1e-6      # 1.0 (equity) - 0.6 (options)
    assert abs(t.net_vega() - 0.2) < 1e-6
    assert abs(t.net_theta() - 0.1) < 1e-6


def test_counts():
    t = _tracker()
    assert t.equity_position_count == 1
    assert t.options_position_count == 1
    assert t.position_count == 2


def test_short_equity_negative_delta():
    t = PortfolioGreeksTracker()
    t.add_equity_position("TSLA", 200, "short")
    assert t.net_delta() < 0


def test_flags():
    t = PortfolioGreeksTracker()
    t.add_options_position("SPY", delta=0.10, vega=0.05, theta=0.0, qty=1)
    assert t.is_delta_neutral() is True        # |0.10| < 0.15
    t.add_options_position("QQQ", delta=0.30, vega=0.0, theta=0.0, qty=1)
    assert t.needs_hedge() is True             # 0.40 > 0.30
    t.add_options_position("IWM", delta=0.0, vega=0.20, theta=0.0, qty=1)
    assert t.vega_at_limit() is True           # 0.25 > 0.15


def test_remove_and_clear():
    t = _tracker()
    t.remove_position("SPY")
    assert t.options_position_count == 0
    t.remove_position("NONEXISTENT")           # no-op, no error
    t.clear()
    assert t.position_count == 0


def test_snapshot_shape():
    snap = _tracker().snapshot()
    for k in ("net_delta", "net_vega", "net_theta", "equity_position_count",
              "options_position_count", "total_position_count", "is_delta_neutral", "needs_hedge"):
        assert k in snap
