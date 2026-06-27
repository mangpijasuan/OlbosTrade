"""Tests for the account mode guard (paper/live fail-closed protection)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import account_guard
from app.services.account_guard import account_is_paper, verify_account_mode


# ── prefix detection ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("acct,expected", [
    ("DU1234567", True),
    ("du1234567", True),
    ("DF7654321", True),
    ("U5559590", False),
    ("U1234567", False),
    ("", False),
    (None, False),
    ("  DU99  ", True),
])
def test_account_is_paper(acct, expected):
    assert account_is_paper(acct) is expected


def _broker(account_id):
    b = AsyncMock()
    b.get_account_summary = AsyncMock(
        return_value=SimpleNamespace(account_id=account_id)
    )
    return b


# ── verify_account_mode ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_paper_config_paper_account_ok():
    with patch.object(account_guard.settings, "ibkr_trading_mode", "paper"):
        ok, detail = await verify_account_mode(_broker("DU123"))
    assert ok is True and "paper" in detail


@pytest.mark.asyncio
async def test_paper_config_live_account_blocked():
    """The dangerous case: think paper, actually live → block."""
    with patch.object(account_guard.settings, "ibkr_trading_mode", "paper"):
        ok, detail = await verify_account_mode(_broker("U5559590"))
    assert ok is False and "LIVE" in detail


@pytest.mark.asyncio
async def test_live_config_paper_account_blocked():
    with patch.object(account_guard.settings, "ibkr_trading_mode", "live"):
        ok, detail = await verify_account_mode(_broker("DU123"))
    assert ok is False and "PAPER" in detail


@pytest.mark.asyncio
async def test_live_config_live_account_ok():
    with patch.object(account_guard.settings, "ibkr_trading_mode", "live"):
        ok, detail = await verify_account_mode(_broker("U999"))
    assert ok is True and "live" in detail


@pytest.mark.asyncio
async def test_unknown_account_fails_closed():
    with patch.object(account_guard.settings, "ibkr_trading_mode", "paper"):
        ok, detail = await verify_account_mode(_broker("unknown"))
    assert ok is False and "unverified" in detail


@pytest.mark.asyncio
async def test_empty_account_fails_closed():
    with patch.object(account_guard.settings, "ibkr_trading_mode", "paper"):
        ok, detail = await verify_account_mode(_broker(""))
    assert ok is False and "unverified" in detail


@pytest.mark.asyncio
async def test_broker_error_fails_closed():
    b = AsyncMock()
    b.get_account_summary = AsyncMock(side_effect=Exception("gateway down"))
    with patch.object(account_guard.settings, "ibkr_trading_mode", "paper"):
        ok, detail = await verify_account_mode(b)
    assert ok is False and "unverified" in detail
