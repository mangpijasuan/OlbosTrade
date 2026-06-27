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


# ── /api/risk/reconciliation ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reconciliation_route_reports_status():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from app.api.routes.risk import get_reconciliation

    fake = SimpleNamespace(
        clean=False, broker_position_count=1, db_open_trade_count=0,
        untracked_at_broker=["SPY"], phantom_in_db=[], warnings=[],
        checked_at=datetime.now(timezone.utc),
    )
    recon = MagicMock()
    recon.check = AsyncMock(return_value=fake)
    with patch("app.broker.broker_factory.get_broker", return_value=MagicMock()), \
         patch("app.services.position_reconciler.PositionReconciler", return_value=recon):
        res = await get_reconciliation()
    assert res["clean"] is False and res["untracked_at_broker"] == ["SPY"]
    assert res["broker_position_count"] == 1 and "checked_at" in res
