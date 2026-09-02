"""
Signal-outcome resolution must be complete, or loudly incomplete.

These rows are the training labels for anything that later learns from signal
outcomes, so the selection of *which* signals get resolved has to be a property
of the signals — never of how far the job happened to get before something
killed it.

It was the latter. Confirmed in production 2026-08-27/28: the scheduler logged
`Scheduler task 'signal_outcomes' timed out after 120s — skipped` on
consecutive runs, and only 32 of 102 tickers had ever received a single label.
The other 70 had none. The resolved subset looked like ordinary data and was
actually a fragment of an interrupted loop, biased toward whichever tickers the
query happened to return first and toward outcomes that resolve fastest
(stop_hit averaged 4.4 bars, target_hit 7.6).

Run with: pytest tests/test_signal_outcome_resolution.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.services import signal_outcome_tracker as sot


# ── fixtures ─────────────────────────────────────────────────────────────────

def _row(ticker="AAPL", action="BUY", entry=100.0, stop=95.0, target=110.0,
         days_ago=10):
    return SimpleNamespace(
        id=uuid.uuid4(),
        ticker=ticker,
        action=action,
        entry_price=Decimal(str(entry)),
        stop_price=Decimal(str(stop)),
        target_price=Decimal(str(target)),
        generated_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        status="pending",
    )


def _bars(closes, start_days_ago=9, high_mult=1.0, low_mult=1.0):
    """Daily OHLC frame indexed by date, walking forward from the signal."""
    idx = [
        (datetime.now(timezone.utc) - timedelta(days=start_days_ago - i)).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        for i in range(len(closes))
    ]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * high_mult for c in closes],
            "Low": [c * low_mult for c in closes],
            "Close": closes,
        },
        index=pd.DatetimeIndex(idx),
    )


class _CaptureSession:
    """Records every execute() so the test can count statements, which is the
    whole point: the old code issued one transaction per row."""

    calls: list = []

    def __init__(self):
        type(self).calls = type(self).calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def begin(self):
        return self

    async def execute(self, stmt, params=None):
        type(self).calls.append((stmt, params))
        result = MagicMock()
        result.scalars.return_value = MagicMock(all=lambda: [])
        return result


# ── the core regression: batched writes ──────────────────────────────────────

@pytest.mark.asyncio
async def test_resolution_does_not_issue_one_write_per_row():
    """The defect that stalled the job.

    2,000 pending rows must not produce anything like 2,000 write statements.
    The old implementation opened a session AND a transaction per row, which is
    why a ~65k backlog could not finish inside any sane budget.
    """
    rows = [_row(ticker=f"T{i // 200}") for i in range(2000)]

    load = MagicMock()
    load.scalars.return_value = MagicMock(all=lambda: rows)

    writes: list = []
    sessions = {"opened": 0}

    class _Session:
        def __init__(self):
            sessions["opened"] += 1
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def begin(self): return self
        async def execute(self, stmt, params=None):
            writes.append((stmt, params))
            return load
        async def get(self, model, pk):        # the old per-row access path
            writes.append(("get", pk))
            return MagicMock()

    with patch("app.core.database.AsyncSessionLocal", _Session), \
         patch.object(sot, "_fetch_daily_bars",
                      new=AsyncMock(return_value=_bars([100.0] * 5))):
        summary = await sot.check_pending_outcomes()

    # Session count is the direct measure of the defect: the old code opened
    # one session and one transaction per row, so 2000 rows meant 2000 of them.
    assert sessions["opened"] < 20, (
        f"expected a handful of sessions, got {sessions['opened']} for 2000 rows"
    )
    # `get` is counted too, so a regression to per-row ORM access trips this
    # even if it were somehow batched into fewer sessions.
    assert len(writes) < 50, (
        f"expected batched writes, got {len(writes)} statements for 2000 rows"
    )
    assert summary["checked"] == 2000


# ── truncation must be visible ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deadline_stops_cleanly_and_reports_truncation():
    """A pass that runs out of budget must say so.

    Silence here is the actual bug: a partial label set is indistinguishable
    from a complete one unless the job reports its own coverage.
    """
    rows = [_row(ticker=f"T{i}") for i in range(40)]
    load = MagicMock()
    load.scalars.return_value = MagicMock(all=lambda: rows)

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def begin(self): return self
        async def execute(self, stmt, params=None): return load

    # Let real time elapse via a slow fetch rather than patching the clock.
    # `time.monotonic` is the same object asyncio's event loop schedules on, so
    # swapping it out underneath an async test corrupts the loop's own timers.
    import asyncio as _asyncio

    async def _slow_fetch(ticker, start):
        await _asyncio.sleep(0.02)
        return _bars([100.0] * 3)

    with patch("app.core.database.AsyncSessionLocal", _Session), \
         patch.object(sot, "_fetch_daily_bars", new=_slow_fetch):
        summary = await sot.check_pending_outcomes(deadline_seconds=0.05)

    assert summary["truncated"] is True
    assert summary["tickers_covered"] < summary["tickers_total"]
    assert summary["tickers_total"] == 40


@pytest.mark.asyncio
async def test_full_coverage_is_not_flagged_truncated():
    rows = [_row(ticker="AAPL"), _row(ticker="MSFT")]
    load = MagicMock()
    load.scalars.return_value = MagicMock(all=lambda: rows)

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def begin(self): return self
        async def execute(self, stmt, params=None): return load

    with patch("app.core.database.AsyncSessionLocal", _Session), \
         patch.object(sot, "_fetch_daily_bars",
                      new=AsyncMock(return_value=_bars([100.0] * 3))):
        summary = await sot.check_pending_outcomes(deadline_seconds=600.0)

    assert summary["truncated"] is False
    assert summary["tickers_covered"] == summary["tickers_total"] == 2


@pytest.mark.asyncio
async def test_oldest_backlog_is_processed_first():
    """Fairness across runs.

    If a truncated pass always walked the same order, the same tickers would be
    starved forever — which is exactly what left 70 of 102 with zero labels.
    Ordering by oldest pending signal means each run drains the worst backlog.
    """
    fresh = _row(ticker="FRESH", days_ago=1)
    stale = _row(ticker="STALE", days_ago=30)
    load = MagicMock()
    load.scalars.return_value = MagicMock(all=lambda: [fresh, stale])

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def begin(self): return self
        async def execute(self, stmt, params=None): return load

    seen: list[str] = []

    async def _fetch(ticker, start):
        seen.append(ticker)
        return _bars([100.0] * 3)

    with patch("app.core.database.AsyncSessionLocal", _Session), \
         patch.object(sot, "_fetch_daily_bars", new=_fetch):
        await sot.check_pending_outcomes()

    assert seen[0] == "STALE", f"oldest backlog must go first, got {seen}"


# ── resolution correctness (unchanged behaviour, now pinned) ─────────────────

def test_target_hit_is_detected():
    row = _row(entry=100.0, stop=95.0, target=110.0)
    hist = _bars([100.0, 105.0, 112.0], high_mult=1.0, low_mult=1.0)
    out = sot._resolve_one(row, hist, max_hold_days=20)
    assert out is not None and out[0] == "target_hit"


def test_stop_hit_is_detected():
    row = _row(entry=100.0, stop=95.0, target=110.0)
    hist = _bars([100.0, 98.0, 94.0])
    out = sot._resolve_one(row, hist, max_hold_days=20)
    assert out is not None and out[0] == "stop_hit"


def test_stop_wins_when_both_cross_on_one_bar():
    """Documented conservative tie-break: a daily bar gives no intraday path,
    so a bar spanning both barriers is booked as the loss."""
    row = _row(entry=100.0, stop=95.0, target=110.0)
    hist = _bars([100.0, 100.0], high_mult=1.15, low_mult=0.90)
    out = sot._resolve_one(row, hist, max_hold_days=20)
    assert out is not None and out[0] == "stop_hit"


def test_expired_fires_at_the_horizon():
    """The timeout class must be reachable. In production it had never once
    fired — max bars elapsed was 9 against a 20-bar horizon — so a third of the
    label space was missing purely because the data was too young."""
    row = _row(entry=100.0, stop=95.0, target=110.0, days_ago=40)
    hist = _bars([100.0] * 25, start_days_ago=30)
    out = sot._resolve_one(row, hist, max_hold_days=20)
    assert out is not None and out[0] == "expired"
    assert out[3] == 20


def test_unresolved_returns_none_rather_than_guessing():
    row = _row(entry=100.0, stop=95.0, target=110.0)
    hist = _bars([100.0, 101.0, 99.0])
    assert sot._resolve_one(row, hist, max_hold_days=20) is None


def test_short_signals_use_inverted_barriers():
    row = _row(action="SELL", entry=100.0, stop=105.0, target=90.0)
    hist = _bars([100.0, 95.0, 88.0])
    out = sot._resolve_one(row, hist, max_hold_days=20)
    assert out is not None and out[0] == "target_hit"


def test_bars_on_or_before_entry_day_are_ignored():
    """Look-ahead guard: the signal's own bar cannot resolve it."""
    row = _row(entry=100.0, stop=95.0, target=110.0, days_ago=2)
    # A bar dated before the signal that would have hit the target.
    hist = _bars([200.0], start_days_ago=5)
    assert sot._resolve_one(row, hist, max_hold_days=20) is None
