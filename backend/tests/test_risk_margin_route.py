"""Tests for the GET /api/risk/margin endpoint."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.risk import get_margin


def _broker(**kw):
    summary = SimpleNamespace(
        net_liquidation=Decimal(str(kw.get("nl", 100_000))),
        maintenance_margin=kw.get("mm", Decimal("10000")),
        excess_liquidity=kw.get("el", Decimal("90000")),
        buying_power=kw.get("bp", Decimal("200000")),
        init_margin=kw.get("im", Decimal("12000")),
    )
    b = MagicMock()
    b.get_account_summary = AsyncMock(return_value=summary)
    return b


@pytest.mark.asyncio
async def test_margin_route_ok():
    with patch("app.broker.broker_factory.get_broker", return_value=_broker()):
        res = await get_margin()
    assert res["available"] is True and res["status"] == "ok"
    assert res["utilization_pct"] == 10.0


@pytest.mark.asyncio
async def test_margin_route_critical():
    with patch("app.broker.broker_factory.get_broker",
               return_value=_broker(mm=Decimal("85000"), el=Decimal("15000"))):
        res = await get_margin()
    assert res["available"] is True and res["status"] == "critical"


@pytest.mark.asyncio
async def test_margin_route_unavailable_when_not_reported():
    with patch("app.broker.broker_factory.get_broker",
               return_value=_broker(mm=None)):
        res = await get_margin()
    assert res["available"] is False and "did not report" in res["reason"]


@pytest.mark.asyncio
async def test_margin_route_broker_error():
    b = MagicMock()
    b.get_account_summary = AsyncMock(side_effect=Exception("disconnected"))
    with patch("app.broker.broker_factory.get_broker", return_value=b):
        res = await get_margin()
    assert res["available"] is False and "disconnected" in res["reason"]
