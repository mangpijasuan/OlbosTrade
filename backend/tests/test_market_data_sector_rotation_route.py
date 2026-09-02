"""Tests for GET /api/market/sector-rotation (route-level dispatch + error
handling; ranking math is covered separately in
test_sector_rotation_engine.py). Imports app.api.routes.market_data, which
pulls in app.main's import chain — hits the known local py3.9 wall (PEP 604
`Mapped[datetime | None]` syntax); CI (py3.11) is authoritative, per
established practice this session."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_route_returns_engine_result_unchanged():
    from app.api.routes import market_data as route

    fake_result = {
        "as_of": "2026-08-17T00:00:00+00:00",
        "rank_basis": "1M",
        "sectors": [{"ticker": "XLK", "name": "Technology", "returns": {"1D": 0.01}, "rank": 1, "prior_rank": 2, "rank_change": 1}],
        "excluded": [],
        "data_source": "yfinance daily bars",
    }
    with patch("app.services.sector_rotation_engine.get_sector_rotation", new=AsyncMock(return_value=fake_result)):
        out = await route.get_sector_rotation()

    assert out == fake_result


@pytest.mark.asyncio
async def test_route_degrades_to_error_payload_not_500():
    from app.api.routes import market_data as route

    with patch("app.services.sector_rotation_engine.get_sector_rotation", new=AsyncMock(side_effect=Exception("yfinance unreachable"))):
        out = await route.get_sector_rotation()

    assert "error" in out and "yfinance unreachable" in out["error"]
    assert out["sectors"] == []
    assert out["excluded"] == []
