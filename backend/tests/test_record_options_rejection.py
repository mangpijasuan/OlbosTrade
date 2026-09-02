"""
_record_options_rejection — writes a scanned-but-not-qualified options
attempt into the same store the Options Signals UI reads. Previously every
rejection reason (entry conditions failing, a confluence conflict,
insufficient data) only ever reached a log line — confirmed on the live
Options Signals page: it showed "0 total" with zero indication of why.
"""

from __future__ import annotations

from app.api.routes.options import _recent_options_signals
from app.main import _record_options_rejection


def _clear():
    _recent_options_signals.clear()


def test_records_a_hold_entry_with_the_reason():
    _clear()
    _record_options_rejection("AAPL", "Price below 20-day SMA", "bull_call_debit_spread")
    assert len(_recent_options_signals) == 1
    entry = _recent_options_signals[0]
    assert entry["ticker"] == "AAPL"
    assert entry["action"] == "HOLD"
    assert entry["reason"] == "Price below 20-day SMA"
    assert entry["strategy"] == "bull_call_debit_spread"
    assert entry["confidence"] == 0.0


def test_strategy_name_is_optional():
    _clear()
    _record_options_rejection("MSFT", "insufficient price history")
    assert _recent_options_signals[0]["strategy"] is None


def test_newest_inserted_first():
    _clear()
    _record_options_rejection("AAPL", "reason one")
    _record_options_rejection("MSFT", "reason two")
    assert [s["ticker"] for s in _recent_options_signals] == ["MSFT", "AAPL"]


def test_store_capped_at_200_entries():
    _clear()
    for i in range(210):
        _record_options_rejection(f"T{i}", "reason")
    assert len(_recent_options_signals) == 200
    # Newest (most recently inserted) entries survive the trim.
    assert _recent_options_signals[0]["ticker"] == "T209"


def test_evidence_is_recorded_when_provided():
    _clear()
    evidence = {
        "top_positive_factors": [{"feature": "iv_rank", "value": 45.2, "impact": 0.12}],
        "top_negative_factors": [{"feature": "days_to_expiry", "value": 3.0, "impact": -0.08}],
    }
    _record_options_rejection("AAPL", "AI scorer: score 0.05", "bull_put_spread", evidence=evidence)
    assert _recent_options_signals[0]["evidence"] == evidence


def test_evidence_defaults_to_none_when_omitted():
    _clear()
    _record_options_rejection("MSFT", "insufficient price history")
    assert _recent_options_signals[0]["evidence"] is None
