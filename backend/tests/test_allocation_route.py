"""Tests for the /api/portfolio/allocation route."""

from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.services.strategy_health import StrategyHealth, HEALTHY, DEGRADED


def _health(strategy, status, score, vol=0.15, exp=50.0):
    return StrategyHealth(strategy, status, "none", 30, 0.8, exp, 2.0, 3.0, 1, 1.1,
                          ["ok"], score=score, volatility=vol)


@pytest.mark.asyncio
async def test_allocation_route_blended():
    from app.api.routes import portfolio as pmod
    health = [_health("bull_put_spread", HEALTHY, 85),
              _health("iron_condor", HEALTHY, 70)]
    import app.main as m
    m._current_regime = NS(regime=NS(value="normal_mean_revert"))
    with patch("app.api.routes.strategy._evaluate_health",
               new=AsyncMock(return_value=health)):
        out = await pmod.portfolio_allocation(method="blended")
    assert out["regime"] == "normal_mean_revert"
    assert out["method"] == "blended"
    assert sum(out["weights"].values()) + out["cash_weight"] == pytest.approx(1.0, abs=1e-3)


@pytest.mark.asyncio
async def test_allocation_route_excludes_degraded():
    from app.api.routes import portfolio as pmod
    health = [_health("bull_put_spread", HEALTHY, 85),
              _health("iron_condor", DEGRADED, 20)]
    import app.main as m
    m._current_regime = NS(regime=NS(value="normal_mean_revert"))
    with patch("app.api.routes.strategy._evaluate_health",
               new=AsyncMock(return_value=health)):
        out = await pmod.portfolio_allocation(method="performance")
    # degraded strategy gets zero allocation (meta tilt 0 → excluded)
    assert out["weights"].get("iron_condor", 0.0) == 0.0
    assert out["weights"]["bull_put_spread"] > 0


@pytest.mark.asyncio
async def test_allocation_route_unknown_method():
    from app.api.routes import portfolio as pmod
    out = await pmod.portfolio_allocation(method="bogus")
    assert "error" in out and "methods" in out


@pytest.mark.asyncio
async def test_allocation_route_health_error():
    from app.api.routes import portfolio as pmod
    with patch("app.api.routes.strategy._evaluate_health",
               new=AsyncMock(side_effect=Exception("db down"))):
        out = await pmod.portfolio_allocation(method="blended")
    assert "error" in out and out["cash_weight"] == 1.0
