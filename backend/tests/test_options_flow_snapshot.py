"""Tests for the free options-flow snapshot service (no network)."""

import pytest

import app.services.options_flow_snapshot as snap


@pytest.mark.asyncio
async def test_snapshot_disabled_returns_zero(monkeypatch):
    """When the free-snapshot flag is off, run_snapshot is a no-op (no DB/network)."""
    monkeypatch.setattr(snap.settings, "options_flow_free_snapshot_enabled", False)
    assert await snap.run_snapshot() == 0


def test_scan_maps_unusual_rows(monkeypatch):
    """_scan_symbol keeps only strikes above the vol/OI and premium thresholds,
    and maps calls->bullish / puts->bearish. yfinance is fully mocked."""
    import pandas as pd

    calls = pd.DataFrame([
        {"strike": 100.0, "lastPrice": 5.0, "volume": 1000, "openInterest": 100, "impliedVolatility": 0.30},  # vol/OI 10, $500k -> keep
        {"strike": 105.0, "lastPrice": 0.10, "volume": 5, "openInterest": 5000, "impliedVolatility": 0.20},   # tiny -> drop
    ])
    puts = pd.DataFrame([
        {"strike": 90.0, "lastPrice": 4.0, "volume": 2000, "openInterest": 200, "impliedVolatility": 0.40},   # vol/OI 10, $800k -> keep
    ])

    class _Chain:
        def __init__(self): self.calls, self.puts = calls, puts

    class _Ticker:
        options = ["2026-12-18"]
        def option_chain(self, exp): return _Chain()

    import types, sys
    fake_yf = types.SimpleNamespace(Ticker=lambda s: _Ticker())
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    rows = snap._scan_symbol("XYZ", max_dte=3650, min_vol_oi=1.5, min_premium=50_000.0)
    assert len(rows) == 2  # one call + one put kept, tiny one dropped
    by_right = {r["right"]: r for r in rows}
    assert by_right["C"]["sentiment"] == "bullish"
    assert by_right["P"]["sentiment"] == "bearish"
    assert float(by_right["C"]["relative_volume"]) == 10.0
    assert float(by_right["C"]["premium"]) == 500_000.0
