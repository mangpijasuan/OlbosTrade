"""Tests for GET /api/risk/var — spot price must be real or the route must
say so, never a fabricated constant."""

from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_spot_cache():
    from app.services import spot_price_cache
    spot_price_cache.clear()
    yield
    spot_price_cache.clear()


@pytest.fixture(autouse=True)
def _reset_main_globals():
    import app.main as m
    prev_tracker, prev_regime = m._greeks_tracker, m._current_regime
    yield
    m._greeks_tracker, m._current_regime = prev_tracker, prev_regime


@pytest.mark.asyncio
async def test_resolved_spot_returns_real_var_and_provenance():
    from app.api.routes import risk as risk_mod
    import app.main as m

    m._greeks_tracker = NS(net_delta=lambda: 0.5, net_vega=lambda: 10.0)
    m._current_regime = NS(features_used=NS(vix=20.0))

    with patch.object(risk_mod, "_fetch_spot", new=AsyncMock(return_value=452.31)):
        out = await risk_mod.get_var()

    assert out["available"] is True
    assert out["spot_price"] == 452.31
    assert out["spot_source"] == "SPY"
    assert out["spot_data_status"] == "LIVE"
    assert out["var"] is not None
    assert out["var"] > 0


@pytest.mark.asyncio
async def test_cached_spot_is_reused_across_calls():
    from app.api.routes import risk as risk_mod
    import app.main as m

    m._greeks_tracker = None
    m._current_regime = None
    call_count = 0

    async def fake_fetch(symbol):
        nonlocal call_count
        call_count += 1
        return 450.0

    with patch.object(risk_mod, "_fetch_spot", new=fake_fetch):
        first = await risk_mod.get_var()
        second = await risk_mod.get_var()

    assert first["spot_data_status"] == "LIVE"
    assert second["spot_data_status"] == "DEGRADED"
    assert call_count == 1


@pytest.mark.asyncio
async def test_cold_cache_and_fetch_failure_returns_unavailable_not_fabricated():
    from app.api.routes import risk as risk_mod
    import app.main as m

    m._greeks_tracker = None
    m._current_regime = None

    with patch.object(risk_mod, "_fetch_spot", new=AsyncMock(side_effect=ConnectionError("yfinance down"))):
        out = await risk_mod.get_var()

    assert out["available"] is False
    assert out["var"] is None
    assert out["expected_shortfall"] is None
    assert out["var_pct"] is None
    assert out["es_pct"] is None
    assert "yfinance down" in out["reason"]


@pytest.mark.asyncio
async def test_greeks_tracker_unavailable_falls_back_to_zero_exposure():
    from app.api.routes import risk as risk_mod
    import app.main as m

    m._greeks_tracker = None
    m._current_regime = None

    with patch.object(risk_mod, "_fetch_spot", new=AsyncMock(return_value=452.31)):
        out = await risk_mod.get_var()

    assert out["available"] is True
    assert out["var"] == 0.0  # zero delta/vega → zero sigma → zero VaR, still a real (not fabricated) result
