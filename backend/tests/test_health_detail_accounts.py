"""
Tests for the IBKR account identity block on GET /api/health/detail.

Added 2026-08-27: a position-count disagreement (app reported 9 open, the
operator's brokerage view showed 6) survived a full backend restart, ruling
out a stale local cache and leaving "the gateway is logged into a different
account than the one being looked at" as a hypothesis that nothing in the
logs or any route could confirm. This exposes the connected account list,
masked, so it can be compared against a brokerage view.

Run with: pytest tests/test_health_detail_accounts.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _broker(accounts, connected=True):
    b = MagicMock()
    b._connected = connected
    b.ib = MagicMock()
    b.ib.isConnected = MagicMock(return_value=connected)
    b.ib.managedAccounts = MagicMock(return_value=accounts)
    return b


def _db_ok():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock())
    return session


async def _call(broker):
    from app.main import health_detail

    with patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_ok()):
        return await health_detail()


@pytest.mark.asyncio
async def test_account_is_masked_to_last_four():
    out = await _call(_broker(["DU1234567"]))

    assert out["ibkr"]["accounts"] == ["****4567"]
    assert out["ibkr"]["account_count"] == 1
    # The full account number must never appear anywhere in the response —
    # this endpoint is unauthenticated.
    assert "DU1234567" not in str(out)


@pytest.mark.asyncio
async def test_multiple_managed_accounts_all_reported():
    """More than one account means position reads may not be scoped to the
    account being compared against — the operator needs to see that."""
    out = await _call(_broker(["DU1234567", "DU7654321"]))

    assert out["ibkr"]["accounts"] == ["****4567", "****4321"]
    assert out["ibkr"]["account_count"] == 2


@pytest.mark.asyncio
async def test_short_account_id_fully_masked():
    out = await _call(_broker(["AB12"]))

    assert out["ibkr"]["accounts"] == ["****"]
    assert "AB12" not in str(out)


@pytest.mark.asyncio
async def test_empty_account_strings_are_skipped():
    out = await _call(_broker(["DU1234567", "", "   "]))

    assert out["ibkr"]["accounts"] == ["****4567"]
    assert out["ibkr"]["account_count"] == 1


@pytest.mark.asyncio
async def test_no_managed_accounts_reports_empty_not_error():
    out = await _call(_broker([]))

    assert out["ibkr"]["accounts"] == []
    assert out["ibkr"]["account_count"] == 0
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_managed_accounts_raising_does_not_break_health():
    """Diagnostics must never take the health endpoint down."""
    b = _broker(["DU1234567"])
    b.ib.managedAccounts = MagicMock(side_effect=Exception("not connected"))

    out = await _call(b)

    assert out["ibkr"]["accounts"] == []
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_trading_mode_is_reported():
    out = await _call(_broker(["DU1234567"]))

    # Confirms which side of the paper/live split this process is on.
    assert out["ibkr"]["trading_mode"] in ("paper", "live")
