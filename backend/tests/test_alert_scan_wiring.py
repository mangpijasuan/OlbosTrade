"""Confirms evaluate_symbol() is wired into the live equity scan path,
with the correct metric-key mapping — the actual regression this closes
(alert rules previously had no automatic caller anywhere in the app)."""

from __future__ import annotations

import inspect


def _alert_snapshot_block() -> str:
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_equity_scan)
    start = src.index("alert_snapshot = {")
    end = src.index("}", start)
    return src[start:end + 1]


def test_evaluate_symbol_called_after_indicators_computed():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_equity_scan)
    assert "evaluate_symbol" in src

    ind_guard_idx = src.index("if not ind:")
    call_idx = src.index("await evaluate_symbol(")
    assert ind_guard_idx < call_idx, (
        "evaluate_symbol must be called after ind is confirmed non-empty, "
        "not before"
    )


def test_alert_snapshot_maps_price_and_rsi_explicitly():
    block = _alert_snapshot_block()
    # ind's own keys are "close"/"rsi" — the snapshot must map them
    # explicitly to "price"/"rsi_14", not assume a matching key name
    # (this codebase already shipped a silent key-mismatch bug from
    # skipping this exact step: sharpe vs sharpe_ratio).
    assert 'ind["close"]' in block
    assert 'ind["rsi"]' in block


def test_alert_snapshot_never_maps_volume_ratio_to_volume():
    block = _alert_snapshot_block()
    # volume_ratio is a ratio to the 20-bar average, not raw volume —
    # mapping it to the "volume" metric would misrepresent the value.
    # (Checks for an actual dict access, not the bare word — the block's
    # own comment explaining this legitimately mentions "volume_ratio".)
    assert 'ind["volume_ratio"]' not in block
    assert 'ind.get("volume_ratio"' not in block
    assert 'df["volume"].iloc[-1]' in block


def test_alert_evaluation_failure_is_isolated_from_the_scan():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_equity_scan)
    # The alert block must have its own try/except immediately preceding
    # the evaluate_symbol call — an alerts bug must never propagate up
    # and drop the ticker's real trading signal for that cycle.
    call_idx = src.index("await evaluate_symbol(")
    preceding = src[:call_idx]
    try_idx = preceding.rindex("try:")
    except_idx = src.index("except Exception as exc:", call_idx)
    assert try_idx < call_idx < except_idx
