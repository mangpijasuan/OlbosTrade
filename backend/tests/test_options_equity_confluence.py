"""
_equity_confluence_reason — blocks an options strategy from firing when it
actively conflicts with this same ticker's own, independently-computed
equity signal (different indicator set, different scoring). Confirmed in
production: options had fired exactly once, ever, because every symbol's
entry gate was checked against one shared market-wide RSI/ADX/IV rank
instead of each stock's own — this confluence check is the other half of
that fix, so an options entry and the same stock's equity read are checked
against each other, not just each computed correctly in isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.main import _equity_confluence_reason


def _signal(ticker: str, action: str, generated_at: datetime) -> dict:
    return {"ticker": ticker, "action": action, "generated_at": generated_at.isoformat()}


def test_no_equity_signal_for_ticker_does_not_block():
    now = datetime.now(timezone.utc)
    signals = [_signal("MSFT", "BUY", now)]
    reason = _equity_confluence_reason("AAPL", "bull_put_spread", signals, now)
    assert reason is None


def test_agreeing_equity_signal_does_not_block():
    now = datetime.now(timezone.utc)
    signals = [_signal("AAPL", "BUY", now)]
    reason = _equity_confluence_reason("AAPL", "bull_put_spread", signals, now)
    assert reason is None


def test_hold_equity_signal_does_not_block():
    """A HOLD reading is inconclusive, not a contradiction."""
    now = datetime.now(timezone.utc)
    signals = [_signal("AAPL", "HOLD", now)]
    reason = _equity_confluence_reason("AAPL", "bear_call_spread", signals, now)
    assert reason is None


def test_bullish_strategy_blocked_by_fresh_sell_signal():
    now = datetime.now(timezone.utc)
    signals = [_signal("AAPL", "SELL", now)]
    reason = _equity_confluence_reason("AAPL", "bull_put_spread", signals, now)
    assert reason is not None
    assert "SELL" in reason


def test_bull_call_debit_spread_also_treated_as_bullish():
    now = datetime.now(timezone.utc)
    signals = [_signal("AAPL", "SELL", now)]
    reason = _equity_confluence_reason("AAPL", "bull_call_debit_spread", signals, now)
    assert reason is not None


def test_bearish_strategy_blocked_by_fresh_buy_signal():
    now = datetime.now(timezone.utc)
    signals = [_signal("AAPL", "BUY", now)]
    reason = _equity_confluence_reason("AAPL", "bear_call_spread", signals, now)
    assert reason is not None
    assert "BUY" in reason


def test_bearish_strategy_not_blocked_by_sell_signal():
    """A SELL equity signal agrees with (doesn't oppose) a bearish options
    strategy — no conflict."""
    now = datetime.now(timezone.utc)
    signals = [_signal("AAPL", "SELL", now)]
    reason = _equity_confluence_reason("AAPL", "bear_call_spread", signals, now)
    assert reason is None


def test_stale_opposing_signal_does_not_block():
    """Missing/stale equity data must never itself block options — this is
    a confirming filter, not a hard prerequisite."""
    now = datetime.now(timezone.utc)
    stale = now - timedelta(hours=2)
    signals = [_signal("AAPL", "SELL", stale)]
    reason = _equity_confluence_reason("AAPL", "bull_put_spread", signals, now, staleness_seconds=3600)
    assert reason is None


def test_only_the_most_recent_signal_for_the_ticker_is_checked():
    """recent_equity_signals is newest-first — an older opposing signal
    behind a newer agreeing one must not trigger a block."""
    now = datetime.now(timezone.utc)
    signals = [
        _signal("AAPL", "BUY", now),                        # newest — agrees
        _signal("AAPL", "SELL", now - timedelta(minutes=15)),  # older — opposes
    ]
    reason = _equity_confluence_reason("AAPL", "bull_put_spread", signals, now)
    assert reason is None


def test_malformed_timestamp_fails_open_not_closed():
    now = datetime.now(timezone.utc)
    signals = [{"ticker": "AAPL", "action": "SELL", "generated_at": "not-a-timestamp"}]
    reason = _equity_confluence_reason("AAPL", "bull_put_spread", signals, now)
    assert reason is None
