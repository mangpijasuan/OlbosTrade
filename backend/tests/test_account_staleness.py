"""
The account-values cache must not be able to present frozen numbers as live.

IBKR serves account data from a local dict that TWS pushes into. Reading it
cannot fail and cannot time out, so a dead push stream looks exactly like a
quiet market: the last-known NetLiquidation, margin and buying power keep
being returned, indefinitely, with nothing to distinguish them from current
ones.

That mattered on 2026-08-27. get_account_summary() was fixed that day to stop
awaiting a subscribe that never completed and to serve the already-populated
cache instead — correct, and it restored real equity and margin figures. But
it also removed the only thing that had been (accidentally) failing loudly.
From then on every account read succeeds, whether or not the numbers behind it
are still moving.

These tests pin the clock that separates the two.

Run with: pytest tests/test_account_staleness.py -v
"""

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker.ibkr_client import (
    ACCOUNT_VALUES_STALE_AFTER_SECONDS,
    IBKRClient,
)


@pytest.fixture
def client():
    c = IBKRClient()
    c._connected = True
    c.ib.isConnected = MagicMock(return_value=True)
    return c


def _pushed_ago(client, seconds: float) -> None:
    """Backdate the last push by `seconds`.

    Deliberately sets the timestamp directly rather than patching
    time.monotonic: `app.broker.ibkr_client.time` IS the stdlib time module,
    so patching its attribute would swap the clock out from under asyncio's
    event loop as well — the timers these async tests depend on.
    """
    client._account_values_last_push = time.monotonic() - seconds


def _account_values():
    return [
        MagicMock(tag="NetLiquidation", value="253348.77", currency="USD"),
        MagicMock(tag="TotalCashValue", value="20000.00", currency="USD"),
        MagicMock(tag="BuyingPower", value="340721.96", currency="USD"),
        MagicMock(tag="MaintMarginReq", value="144909.36", currency="USD"),
        MagicMock(tag="ExcessLiquidity", value="108102.18", currency="USD"),
    ]


# ── The age clock itself ──────────────────────────────────────────────────────

def test_never_pushed_reports_no_age_and_is_not_stale(client):
    """A cache nothing has ever arrived in is empty, not stale.

    The distinction matters: callers already handle "no data" correctly. Only
    real-looking-but-frozen data is the new hazard, so an untouched client must
    not raise a false alarm.
    """
    assert client.account_values_age_seconds() is None
    assert client.account_values_are_stale() is False


def test_a_push_starts_the_clock(client):
    client._on_account_value()
    age = client.account_values_age_seconds()
    assert age is not None and age < 1.0
    assert client.account_values_are_stale() is False


def test_age_reflects_how_long_ago_the_push_was(client):
    _pushed_ago(client, 42.0)
    assert client.account_values_age_seconds() == pytest.approx(42.0, abs=1.0)


def test_data_goes_stale_past_the_threshold(client):
    _pushed_ago(client, ACCOUNT_VALUES_STALE_AFTER_SECONDS - 30)
    assert client.account_values_are_stale() is False, (
        "inside the limit is still live"
    )

    _pushed_ago(client, ACCOUNT_VALUES_STALE_AFTER_SECONDS + 30)
    assert client.account_values_are_stale() is True


def test_a_fresh_push_clears_staleness(client):
    """Recovery must be automatic — a stream that resumes is live again."""
    _pushed_ago(client, ACCOUNT_VALUES_STALE_AFTER_SECONDS + 500)
    assert client.account_values_are_stale() is True

    client._on_account_value()
    assert client.account_values_are_stale() is False


def test_the_event_handler_never_raises(client):
    """It runs inside ib_insync's message dispatch. An exception escaping here
    would break the client's message loop — far worse than a missing timestamp.

    Patching the clock is safe in this one test only because it is synchronous:
    no event loop is running, so nothing else is reading time.monotonic for the
    duration of the call. The async tests below use _pushed_ago instead.
    """
    with patch("app.broker.ibkr_client.time.monotonic",
               side_effect=RuntimeError("clock unavailable")):
        client._on_account_value()  # must not raise

    assert client.account_values_age_seconds() is None


# ── Connection lifecycle ──────────────────────────────────────────────────────

def test_reconnect_clears_the_timestamp(client):
    """The push timestamp belongs to the socket that produced it.

    Carrying it across a reconnect would describe the new, empty cache as
    freshly updated — reporting maximum confidence at exactly the moment there
    is nothing to be confident about.
    """
    client._on_account_value()
    assert client.account_values_age_seconds() is not None

    client._reset_account_subscription()
    assert client.account_values_age_seconds() is None
    assert client.account_values_are_stale() is False


def test_handler_is_registered_once_not_per_connection():
    """self.ib outlives connect()/disconnect() cycles, so hooking the event
    per-connection would stack duplicate handlers and call each one."""
    c = IBKRClient()
    before = len(c.ib.accountValueEvent)

    c._reset_account_subscription()
    c._reset_account_subscription()

    assert len(c.ib.accountValueEvent) == before


# ── The figures carry their own age ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_reports_age_and_freshness(client):
    client.ib.accountValues = MagicMock(return_value=_account_values())
    client.ib.managedAccounts = MagicMock(return_value=["DU123456"])
    client.ib.reqAccountUpdatesAsync = AsyncMock(return_value=None)

    _pushed_ago(client, 30.0)
    summary = await client.get_account_summary()

    assert summary.data_age_seconds == pytest.approx(30.0, abs=1.0)
    assert summary.is_stale is False
    assert summary.net_liquidation == Decimal("253348.77")


@pytest.mark.asyncio
async def test_stale_summary_is_flagged_but_still_returned(client):
    """Withholding the numbers would recreate the blackout this cache-serving
    path was built to end. Display still needs the last-known figures — they
    just have to arrive labelled, so nothing downstream can mistake them for
    current."""
    client.ib.accountValues = MagicMock(return_value=_account_values())
    client.ib.managedAccounts = MagicMock(return_value=["DU123456"])
    client.ib.reqAccountUpdatesAsync = AsyncMock(return_value=None)

    _pushed_ago(client, ACCOUNT_VALUES_STALE_AFTER_SECONDS + 60)
    summary = await client.get_account_summary()

    assert summary.is_stale is True
    assert summary.data_age_seconds > ACCOUNT_VALUES_STALE_AFTER_SECONDS
    assert summary.net_liquidation == Decimal("253348.77")
    assert summary.maintenance_margin == Decimal("144909.36")


@pytest.mark.asyncio
async def test_summary_age_is_none_when_nothing_ever_pushed(client):
    """Cache populated by some other means, clock never started: report the
    age as unknown rather than inventing a fresh one."""
    client.ib.accountValues = MagicMock(return_value=_account_values())
    client.ib.managedAccounts = MagicMock(return_value=["DU123456"])
    client.ib.reqAccountUpdatesAsync = AsyncMock(return_value=None)

    summary = await client.get_account_summary()

    assert summary.data_age_seconds is None
    assert summary.is_stale is False


def test_default_summary_is_not_silently_marked_fresh():
    """Brokers that report no age must not be assumed current. is_stale
    defaults False (unknown age is not evidence of staleness), but
    data_age_seconds must stay None rather than defaulting to 0."""
    from app.broker.broker_interface import AccountSummary

    s = AccountSummary(
        account_id="DU1",
        net_liquidation=Decimal("1"),
        cash_balance=Decimal("1"),
        buying_power=Decimal("1"),
    )
    assert s.data_age_seconds is None
    assert s.is_stale is False
