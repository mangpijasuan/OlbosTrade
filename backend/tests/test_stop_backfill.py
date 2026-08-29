"""Tests for recovering missing equity stops from the live order book.

This module writes a number the risk gates then trust, and every write lowers
measured risk. So the interesting cases are the refusals, not the happy path.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.stop_backfill import backfill_equity_stops


def _stop(symbol, action, remaining, stop_price):
    return {"symbol": symbol, "action": action, "remaining": remaining,
            "stop_price": stop_price, "is_protective": True, "order_type": "STP"}


def _trade(ticker="LITE", entry=887.22, qty=68, direction="equity_long",
           long_strike=None, trade_id="t1"):
    """Open equity row. long_strike defaults to the placeholder shape the
    reconciler writes: identical to entry, meaning no stop was ever recorded."""
    return NS(id=trade_id, underlying=ticker, spread_type=direction,
              status="open", quantity=qty,
              credit_received=Decimal(str(entry)),
              short_strike=Decimal(str(entry)),
              long_strike=Decimal(str(entry if long_strike is None else long_strike)),
              strategy="equity")


def _broker(orders, positions):
    b = MagicMock()
    b.get_open_orders = AsyncMock(return_value={"source": "refreshed", "orders": orders})
    b.get_equity_positions = AsyncMock(return_value=[
        NS(symbol=s, quantity=q) for s, q in positions.items()])
    return b


def _session(trades):
    s = AsyncMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: trades)
    s.execute = AsyncMock(return_value=result)
    s.commit = AsyncMock()
    return s


async def _run(trades, orders, positions, dry_run=True):
    session = _session(trades)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        report = await backfill_equity_stops(
            _broker(orders, positions), dry_run=dry_run)
    return report, session


# ── The happy path, with the real production numbers ────────────────────

@pytest.mark.asyncio
async def test_blended_stop_reproduces_the_tranches_exact_dollar_risk():
    """LITE's three tranches blend to 726.325, and 68 x (887.22 - 726.325) is
    the same $10,940.86 the tranches sum to individually."""
    t = _trade()
    orders = [_stop("LITE", "SELL", 23, 709.14),
              _stop("LITE", "SELL", 23, 709.96),
              _stop("LITE", "SELL", 22, 761.40)]
    report, session = await _run([t], orders, {"LITE": 68}, dry_run=False)

    assert report["status"] == "ok"
    assert report["submitted_anything"] is False
    (row,) = report["updated"]
    assert row["ticker"] == "LITE"
    assert row["tranches"] == 3
    assert row["stop_price"] == pytest.approx(726.325, abs=1e-3)

    by_tranche = (23 * (887.22 - 709.14) + 23 * (887.22 - 709.96)
                  + 22 * (887.22 - 761.40))
    assert row["risk_after"] == pytest.approx(by_tranche, abs=0.01)
    assert row["risk_before"] == pytest.approx(887.22 * 68, abs=0.01)

    assert float(t.long_strike) == pytest.approx(726.325, abs=1e-3)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_short_position_takes_a_buy_stop_above_entry():
    t = _trade(ticker="MSTR", entry=126.95, qty=156, direction="equity_short")
    report, _ = await _run([t], [_stop("MSTR", "BUY", 156, 141.20)],
                           {"MSTR": -156}, dry_run=False)
    (row,) = report["updated"]
    assert row["stop_price"] == pytest.approx(141.20)
    assert row["risk_after"] == pytest.approx(156 * 14.25, abs=0.01)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_but_reports_everything():
    t = _trade()
    report, session = await _run(
        [t], [_stop("LITE", "SELL", 68, 726.33)], {"LITE": 68}, dry_run=True)
    assert report["dry_run"] is True
    assert len(report["updated"]) == 1
    assert float(t.long_strike) == pytest.approx(887.22)   # untouched
    session.commit.assert_not_awaited()


# ── The refusals ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_partial_coverage_is_refused():
    """Stops covering 40 of 68 shares leave 28 shares with unbounded risk.
    Blending across the whole position would report that as zero."""
    report, _ = await _run(
        [_trade()], [_stop("LITE", "SELL", 40, 709.14)], {"LITE": 68})
    assert report["updated"] == []
    assert "partial coverage" in report["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_a_recorded_stop_is_never_overwritten():
    t = _trade(ticker="MRVL", entry=234.69, qty=599, long_strike=197.96)
    report, _ = await _run([t], [_stop("MRVL", "SELL", 599, 210.0)],
                           {"MRVL": 599})
    assert report["updated"] == []
    assert "already has a recorded stop" in report["skipped"][0]["reason"]
    assert float(t.long_strike) == pytest.approx(197.96)


@pytest.mark.asyncio
async def test_cached_order_book_refuses_to_write_anything():
    b = _broker([], {})
    b.get_open_orders = AsyncMock(return_value={"source": "cache", "orders": []})
    report = await backfill_equity_stops(b, dry_run=False)
    assert report["status"] == "unavailable"
    assert report["updated"] == []


@pytest.mark.asyncio
async def test_stop_on_the_wrong_side_of_entry_is_refused():
    # A SELL stop above entry for a long is not protecting anything.
    report, _ = await _run(
        [_trade()], [_stop("LITE", "SELL", 68, 900.0)], {"LITE": 68})
    assert report["updated"] == []
    assert "not below entry" in report["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_wrong_action_for_the_direction_is_refused():
    # A BUY stop cannot protect a long position.
    report, _ = await _run(
        [_trade()], [_stop("LITE", "BUY", 68, 709.14)], {"LITE": 68})
    assert report["updated"] == []
    assert "not all SELL" in report["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_no_protective_order_leaves_the_row_alone():
    report, _ = await _run([_trade()], [], {"LITE": 68})
    assert report["updated"] == []
    assert "no protective stop" in report["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_no_live_position_leaves_the_row_alone():
    """Orphaned stops for a symbol we no longer hold must not become a stop
    on a stale row — the 20 orphans in production are exactly this shape."""
    report, _ = await _run(
        [_trade(ticker="ASML", entry=1800.0, qty=11)],
        [_stop("ASML", "SELL", 11, 1630.39)], {})
    assert report["updated"] == []
    assert "no live broker position" in report["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_blended_stop_adjacent_to_entry_is_refused():
    report, _ = await _run(
        [_trade()], [_stop("LITE", "SELL", 68, 887.0)], {"LITE": 68})
    assert report["updated"] == []
    assert "placeholder" in report["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_options_rows_are_not_touched():
    t = NS(id="o1", underlying="SPY", spread_type="put", status="open",
           quantity=2, credit_received=Decimal("1.50"),
           short_strike=Decimal("450"), long_strike=Decimal("445"),
           strategy="bull_put_spread")
    report, _ = await _run([t], [_stop("SPY", "SELL", 2, 440.0)], {"SPY": 2})
    assert report["updated"] == []
    assert report["skipped"] == []          # not a candidate at all
    assert float(t.long_strike) == pytest.approx(445.0)


@pytest.mark.asyncio
async def test_broker_failure_reports_error_and_writes_nothing():
    b = MagicMock()
    b.get_open_orders = AsyncMock(side_effect=RuntimeError("gateway down"))
    report = await backfill_equity_stops(b, dry_run=False)
    assert report["status"] == "error"
    assert "gateway down" in report["reason"]
    assert report["updated"] == []
