"""Confirms record_options_signal() is wired into the live options scan path
— and only there, not into the separate rejection-recording path."""

from __future__ import annotations

import inspect


def test_record_options_signal_called_after_in_memory_insert():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_options_scan)
    assert "record_options_signal" in src

    insert_idx = src.index("_recent_options_signals.insert(0, signal)")
    call_idx = src.index("await record_options_signal(signal)")
    assert insert_idx < call_idx, (
        "record_options_signal must be called after the signal is finalized "
        "and appended to the in-memory store, not before"
    )


def test_record_options_signal_not_called_from_rejection_path():
    import app.main as main_mod

    src = inspect.getsource(main_mod._record_options_rejection)
    assert "record_options_signal" not in src, (
        "rejections have no real spread/evidence data to persist — only "
        "qualifying BUY_SPREAD/SELL_SPREAD signals should reach the DB"
    )
