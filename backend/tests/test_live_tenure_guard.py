"""Tests for the live-capital tenure guard (paper→live fail-closed protection)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import live_tenure_guard
from app.services.live_tenure_guard import (
    TenureStatus, check_live_tenure, verify_live_tenure,
)


def _cfg(*, paper: bool, days: int = 90, trades: int = 20):
    """Patch the settings this guard reads."""
    return (
        patch.object(live_tenure_guard.settings, "ibkr_trading_mode", "paper" if paper else "live"),
        patch.object(live_tenure_guard.settings, "broker", "ibkr"),
        patch.object(live_tenure_guard.settings, "live_min_paper_trading_days", days),
        patch.object(live_tenure_guard.settings, "live_min_paper_closed_trades", trades),
    )


def _apply(patches):
    for p in patches:
        p.start()
    return patches


def _stop(patches):
    for p in patches:
        p.stop()


@pytest.fixture
def live_cfg():
    patches = _apply(_cfg(paper=False))
    yield
    _stop(patches)


@pytest.fixture
def paper_cfg():
    patches = _apply(_cfg(paper=True))
    yield
    _stop(patches)


def _track_record(first_at, finished):
    return patch.object(
        live_tenure_guard, "read_track_record",
        AsyncMock(return_value=(first_at, finished)),
    )


# ── paper mode is a no-op ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_paper_mode_always_allowed(paper_cfg):
    """The gate governs live capital only — it must never block paper trading."""
    with _track_record(None, 0):
        status = await check_live_tenure()
    assert status.allowed is True
    assert status.reason == "paper_mode"

    ok, detail = await verify_live_tenure()
    assert ok is True and "paper mode" in detail


# ── the core case: live with no track record ──────────────────────────────────
@pytest.mark.asyncio
async def test_live_with_no_history_blocked(live_cfg):
    """Day-one live trading — the exact scenario the charter forbids."""
    with _track_record(None, 0):
        status = await check_live_tenure()
        ok, detail = await verify_live_tenure()
    assert status.allowed is False
    assert status.reason == "no_trading_history"
    assert ok is False
    assert "no trading history" in detail


@pytest.mark.asyncio
async def test_live_with_insufficient_days_blocked(live_cfg):
    first = datetime.now(timezone.utc) - timedelta(days=30)
    with _track_record(first, 500):
        status = await check_live_tenure()
        ok, detail = await verify_live_tenure()
    assert status.allowed is False
    assert status.reason == "insufficient_paper_days"
    assert ok is False
    assert "30.0d of 90d" in detail


@pytest.mark.asyncio
async def test_live_with_enough_days_but_too_few_trades_blocked(live_cfg):
    """Time alone is not a track record — an idle install must not pass."""
    first = datetime.now(timezone.utc) - timedelta(days=120)
    with _track_record(first, 3):
        status = await check_live_tenure()
        ok, detail = await verify_live_tenure()
    assert status.allowed is False
    assert status.reason == "insufficient_closed_trades"
    assert ok is False
    assert "3 finished trades of 20 required" in detail


@pytest.mark.asyncio
async def test_live_with_full_track_record_allowed(live_cfg):
    first = datetime.now(timezone.utc) - timedelta(days=120)
    with _track_record(first, 40):
        status = await check_live_tenure()
        ok, detail = await verify_live_tenure()
    assert status.allowed is True
    assert status.reason is None
    assert ok is True
    assert "live tenure met" in detail


@pytest.mark.asyncio
async def test_boundary_exactly_at_thresholds_allowed(live_cfg):
    """Exactly at both floors passes — the rule is a minimum, not a strict >."""
    first = datetime.now(timezone.utc) - timedelta(days=90, minutes=1)
    with _track_record(first, 20):
        status = await check_live_tenure()
    assert status.allowed is True


# ── fail-closed behavior ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_db_error_fails_closed(live_cfg):
    """An unreadable track record must never be the reason real money moves."""
    with patch.object(
        live_tenure_guard, "read_track_record",
        AsyncMock(side_effect=RuntimeError("db down")),
    ):
        ok, detail = await verify_live_tenure()
    assert ok is False
    assert "tenure_unverified" in detail
    assert "db down" in detail


# ── configuration escape hatch ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_gate_disabled_by_zero_config():
    patches = _apply(_cfg(paper=False, days=0, trades=0))
    try:
        with _track_record(None, 0):
            status = await check_live_tenure()
            ok, detail = await verify_live_tenure()
    finally:
        _stop(patches)
    assert status.allowed is True
    assert status.reason == "gate_disabled"
    assert ok is True and "disabled by configuration" in detail


@pytest.mark.asyncio
async def test_days_disabled_but_trade_floor_still_enforced():
    """Zeroing only the day floor must not silently drop the trade floor too."""
    patches = _apply(_cfg(paper=False, days=0, trades=20))
    try:
        first = datetime.now(timezone.utc) - timedelta(days=1)
        with _track_record(first, 2):
            status = await check_live_tenure()
    finally:
        _stop(patches)
    assert status.allowed is False
    assert status.reason == "insufficient_closed_trades"


# ── naive datetime handling ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_naive_first_trade_date_treated_as_utc(live_cfg):
    """Legacy rows can come back naive; that must not crash the guard."""
    naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=200)
    with _track_record(naive, 50):
        status = await check_live_tenure()
    assert status.allowed is True
    assert status.days_elapsed == pytest.approx(200, abs=1)


# ── read_track_record ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_read_track_record_queries_min_date_and_finished_count():
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_Result(first), _Result(7)])

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    with patch("app.core.database.AsyncSessionLocal", lambda: _Ctx()):
        got_first, got_count = await live_tenure_guard.read_track_record()

    assert got_first == first
    assert got_count == 7
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_read_track_record_null_count_coerced_to_zero():
    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_Result(None), _Result(None)])

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    with patch("app.core.database.AsyncSessionLocal", lambda: _Ctx()):
        got_first, got_count = await live_tenure_guard.read_track_record()

    assert got_first is None
    assert got_count == 0


# ── serialization ─────────────────────────────────────────────────────────────
def test_status_as_dict_round_trips_fields():
    first = datetime(2026, 3, 1, tzinfo=timezone.utc)
    d = TenureStatus(
        allowed=False, reason="insufficient_paper_days", days_elapsed=12.5,
        finished_trades=4, required_days=90, required_trades=20, first_trade_at=first,
    ).as_dict()
    assert d["allowed"] is False
    assert d["reason"] == "insufficient_paper_days"
    assert d["days_elapsed"] == 12.5
    assert d["finished_trades"] == 4
    assert d["required_days"] == 90
    assert d["required_trades"] == 20
    assert d["first_trade_at"] == first.isoformat()


def test_status_as_dict_handles_absent_first_trade():
    d = TenureStatus(
        allowed=True, reason="paper_mode", days_elapsed=None, finished_trades=None,
        required_days=90, required_trades=20,
    ).as_dict()
    assert d["first_trade_at"] is None
    assert d["days_elapsed"] is None
