"""Confirms evaluate_symbol() is wired into the live equity AND options scan
paths, with the correct metric-key mapping — the actual regression this
closes (alert rules previously had no automatic caller anywhere in the app
for equity; options alert wiring is Phase 2 track 2A.1)."""

from __future__ import annotations

import inspect


def _source_block(fn, start_marker: str) -> str:
    src = inspect.getsource(fn)
    start = src.index(start_marker)
    end = src.index("}", start)
    return src[start:end + 1]


def _alert_snapshot_block() -> str:
    import app.main as main_mod

    return _source_block(main_mod._run_equity_scan, "alert_snapshot = {")


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


def test_alert_snapshot_includes_alpha_edge_and_opportunity_score():
    block = _alert_snapshot_block()
    assert '"alpha_edge_entry_score"' in block
    assert '"alpha_edge_risk_score"' in block
    assert '"opportunity_score"' in block


def test_alert_snapshot_reuses_alpha_edge_pure_functions_not_reimplemented():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_equity_scan)
    # Entry/risk scores must come from the same functions
    # alpha_edge_engine.compute_equity_alpha_edge() itself calls — not a
    # second, driftable copy of "round(confidence * 100)" etc.
    assert "compute_equity_scores" in src
    assert "from app.services.trade_frequency_controller import risk_score" in src
    # And not the full I/O-bound Alpha Edge orchestrator, which would
    # re-fetch bars/hit the DB for every ticker on every scan cycle.
    # (Checked as an actual call, not a bare substring — this file's own
    # comment legitimately mentions the orchestrator's name for context.)
    assert "compute_equity_alpha_edge(" not in src


def test_opportunity_score_computed_before_alert_snapshot():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_equity_scan)
    opp_score_idx = src.index('signal["opportunity_score"] = compute_opportunity_score(signal)')
    snapshot_idx = src.index("alert_snapshot = {")
    assert opp_score_idx < snapshot_idx


# ── Options scan alert wiring (Phase 2 track 2A.1) ────────────────────────────

def _options_alert_snapshot_block() -> str:
    import app.main as main_mod

    return _source_block(main_mod._run_options_scan, "alert_snapshot = {")


def test_options_scan_calls_evaluate_symbol():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_options_scan)
    assert "evaluate_symbol" in src
    assert "await evaluate_symbol(" in src


def test_options_alert_snapshot_includes_alpha_edge_and_opportunity_score():
    block = _options_alert_snapshot_block()
    assert '"alpha_edge_entry_score"' in block
    assert '"alpha_edge_risk_score"' in block
    assert '"opportunity_score"' in block


def test_options_alert_evaluation_failure_is_isolated_from_the_scan():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_options_scan)
    call_idx = src.index("await evaluate_symbol(")
    preceding = src[:call_idx]
    try_idx = preceding.rindex("try:")
    except_idx = src.index("except Exception as exc:", call_idx)
    assert try_idx < call_idx < except_idx


def test_options_alert_computed_after_opportunity_score():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_options_scan)
    opp_score_idx = src.index('signal["opportunity_score"] = compute_opportunity_score(signal)')
    snapshot_idx = src.index("alert_snapshot = {")
    assert opp_score_idx < snapshot_idx


# ── Liquidity/gamma field threading (Phase 2 track 2A.2) ──────────────────────

def test_live_spread_quote_returns_bid_ask_oi_gamma():
    import app.main as main_mod

    src = inspect.getsource(main_mod._live_spread_quote)
    for key in ("short_bid", "short_ask", "long_bid", "long_ask",
                "short_open_interest", "long_open_interest", "short_gamma"):
        assert f'"{key}"' in src


def test_signal_spread_never_fabricates_liquidity_on_fallback_paths():
    import app.main as main_mod

    src = inspect.getsource(main_mod._run_options_scan)
    # liquidity_data must default to None and only be set on the live_chain
    # branch — never on the yfinance/Black-Scholes fallback paths.
    init_idx = src.index("liquidity_data: Optional[dict] = None")
    live_chain_idx = src.index('credit_source = "live_chain"')
    set_idx = src.index("liquidity_data = live")
    assert init_idx < live_chain_idx < set_idx
