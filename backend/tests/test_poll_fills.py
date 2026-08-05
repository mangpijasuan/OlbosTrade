"""
Regression coverage for _poll_fills' entry-side reconciliation.

Confirmed in production: a pending trade's unfilled-order grace period used
to be tracked in an in-memory dict (`_fill_pending`), keyed off when the
*current process* first noticed the trade -- not the trade's own entry_date.
A backend restart (e.g. a routine deploy) landing mid-grace-period wiped that
dict, resetting the clock and leaving the stuck trade blocking every future
signal for that underlying via the duplicate-open guard for up to another
full FILL_GRACE_SECONDS on top of however long it had already been stuck.

These tests exercise _poll_fills directly against a trade whose entry_date is
already well past the grace window on the *first* call -- proving the
timeout no longer depends on the process having "seen" the trade before.

Also covers a second, separately-confirmed production bug: IBKRClient's
get_positions() reads ib.portfolio(), a purely local cache with no network
round-trip and no exception on staleness. Right after a broker reconnect,
that cache can come back empty *without raising* -- and _poll_fills used to
treat that hollow list as ground truth, concluding every open position had
vanished. Six unrelated open positions (SPY, META, AMZN, NVDA, MSFT, AAPL)
were all wrongly marked closed_price_unavailable within 30ms of each other
in a single poll cycle. _poll_fills must now check the broker's own
connection state and skip the whole reconciliation pass rather than trust an
empty/incomplete position list from a broker that isn't really connected.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as m
from app.services.trade_recorder import trade_recorder


def _db_session(trades):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: trades)
    session.execute = AsyncMock(return_value=result)
    return session


def _fake_broker(positions=None):
    broker = MagicMock()
    broker.get_positions = AsyncMock(return_value=positions or [])
    # No `.ib` attribute → executions fetch is skipped (matches the real
    # try/except fallback for a broker without a live IB client).
    del broker.ib
    return broker


def _pending_trade(entry_date, underlying="NVDA"):
    t = MagicMock()
    t.id = "11111111-1111-1111-1111-111111111111"
    t.status = "pending"
    t.underlying = underlying
    t.entry_date = entry_date
    return t


@pytest.mark.asyncio
async def test_stale_pending_trade_cancelled_on_first_observation():
    # entry_date is far beyond FILL_GRACE_SECONDS in the past -- this must
    # resolve on the very first _poll_fills() call, with no prior in-memory
    # state required (simulates a fresh process right after a restart).
    stale_entry = datetime.now(timezone.utc) - timedelta(
        seconds=m.FILL_GRACE_SECONDS + 60
    )
    trade = _pending_trade(stale_entry)

    with patch("app.broker.broker_factory.get_broker", return_value=_fake_broker()), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([trade])), \
         patch.object(trade_recorder, "cancel_pending", new=AsyncMock()) as cancel, \
         patch.object(trade_recorder, "confirm_fill", new=AsyncMock()) as confirm:
        await m._poll_fills()

    cancel.assert_awaited_once()
    assert cancel.await_args.kwargs["trade_id"] == trade.id
    assert cancel.await_args.kwargs["reason"] == "order_unfilled_timeout"
    confirm.assert_not_called()


@pytest.mark.asyncio
async def test_recent_pending_trade_not_cancelled_yet():
    # entry_date is well within the grace window -- must not be touched.
    recent_entry = datetime.now(timezone.utc) - timedelta(seconds=30)
    trade = _pending_trade(recent_entry)

    with patch("app.broker.broker_factory.get_broker", return_value=_fake_broker()), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([trade])), \
         patch.object(trade_recorder, "cancel_pending", new=AsyncMock()) as cancel, \
         patch.object(trade_recorder, "confirm_fill", new=AsyncMock()) as confirm:
        await m._poll_fills()

    cancel.assert_not_called()
    confirm.assert_not_called()


@pytest.mark.asyncio
async def test_pending_trade_with_live_position_confirmed_not_cancelled():
    # The underlying now shows at the broker -- promote to open, don't cancel,
    # regardless of how long it had been pending.
    stale_entry = datetime.now(timezone.utc) - timedelta(
        seconds=m.FILL_GRACE_SECONDS + 60
    )
    trade = _pending_trade(stale_entry)
    live_position = MagicMock(symbol="NVDA", underlying="NVDA", unrealized_pnl=None)

    with patch("app.broker.broker_factory.get_broker",
               return_value=_fake_broker(positions=[live_position])), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([trade])), \
         patch.object(trade_recorder, "cancel_pending", new=AsyncMock()) as cancel, \
         patch.object(trade_recorder, "confirm_fill", new=AsyncMock()) as confirm:
        await m._poll_fills()

    confirm.assert_awaited_once_with(trade_id=trade.id)
    cancel.assert_not_called()


# ── Broker connection-health guard (IBKR-shaped brokers only) ────────────────

def _ibkr_shaped_broker(*, connected: bool, positions=None):
    """A broker with a real `.ib` attribute, like IBKRClient — the shape
    _poll_fills' connection guard actually checks. Brokers without `.ib`
    (Alpaca, test doubles) skip the guard entirely, per _fake_broker above."""
    broker = MagicMock()
    broker._connected = connected
    broker.ib = MagicMock()
    broker.ib.isConnected.return_value = connected
    broker.get_positions = AsyncMock(return_value=positions or [])
    return broker


def _open_trade(underlying, entry_date):
    t = MagicMock()
    t.id = f"open-{underlying}"
    t.status = "open"
    t.underlying = underlying
    t.entry_date = entry_date
    t.spread_type = "equity_long"
    return t


@pytest.mark.asyncio
async def test_disconnected_broker_skips_reconciliation_entirely():
    """The exact production bug: an empty position list from a broker that
    isn't really connected must never be treated as 'everything closed' —
    six real open positions must survive a cycle where the broker reports
    disconnected, even though get_positions() returned an empty list."""
    entry = datetime.now(timezone.utc) - timedelta(days=1)
    trades = [_open_trade(sym, entry) for sym in ("SPY", "META", "AMZN", "NVDA", "MSFT", "AAPL")]

    broker = _ibkr_shaped_broker(connected=False, positions=[])  # hollow cache

    with patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session(trades)), \
         patch.object(trade_recorder, "record_close_unknown", new=AsyncMock()) as close_unknown, \
         patch.object(trade_recorder, "record_exit", new=AsyncMock()) as record_exit:
        await m._poll_fills()

    broker.get_positions.assert_not_called()  # never even reached
    close_unknown.assert_not_called()
    record_exit.assert_not_called()


@pytest.mark.asyncio
async def test_connected_ibkr_broker_still_reconciles_normally():
    """Sanity check the guard doesn't just disable reconciliation outright —
    a genuinely connected IBKR-shaped broker with a real empty position list
    (a real close) must still proceed as before."""
    stale_entry = datetime.now(timezone.utc) - timedelta(
        seconds=m.FILL_GRACE_SECONDS + 60
    )
    trade = _pending_trade(stale_entry)
    broker = _ibkr_shaped_broker(connected=True, positions=[])

    with patch("app.broker.broker_factory.get_broker", return_value=broker), \
         patch("app.core.database.AsyncSessionLocal", return_value=_db_session([trade])), \
         patch.object(trade_recorder, "cancel_pending", new=AsyncMock()) as cancel:
        await m._poll_fills()

    broker.get_positions.assert_awaited_once()
    cancel.assert_awaited_once()
