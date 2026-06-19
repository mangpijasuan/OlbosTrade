# OlbosQuant — Security/Correctness Audit Tracker

Status legend: ✅ resolved · 🔶 partial · ⬜ open

> Paper/sandbox only. No live-trading enablement until all batches are done and tested.

## Batch 1 — Single fail-closed order pipeline
Every order (signal/autopilot, copilot-approved, manual) now funnels through one gate:
`app/services/order_gate.py` → **kill switch → unified risk → sizing → execution dispatch →
fill-confirmed recording**. Fail-closed: unreadable risk state refuses the trade.

| # | Issue | Status | Note | Test |
|---|-------|--------|------|------|
| 1 | `_execute_signal()` placed orders after only kill-switch + dup checks (no unified risk / sizing / dispatcher) | ✅ | `_execute_signal` now delegates to `order_gate.submit`, which runs all five stages | `test_signal_breach_rejected_no_dispatch`, `test_clean_order_runs_five_stages_in_order` |
| 9 | Manual trade endpoint bypassed all guardrails except kill switch (also called broker directly) | ✅ | `manual_trade` now routes through `_execute_signal` → the gate; 403 on risk block | `test_manual_breach_rejected` |
| 14 | Guardrail DB read defaulted P&L/counts to zero on exception (fail-open) | ✅ | Gate's `_read_portfolio_state` raises → gate refuses; `main.py` guardrail endpoint now returns `trading_allowed=False` on read failure | `test_guardrail_read_raises_fails_closed` |
| 17 | Sizing floored to ≥1 contract (`risk_manager` + `paper_trader`) | ✅ | `risk_manager.calculate_position_size` returns 0 (prior batch); `paper_trader` no longer floors and skips on 0; gate skips on 0 | `test_zero_size_no_order` |
| +A | `_execute_signal` never used `ExecutionDispatcher` (no liquidity/atomic stage) | ✅ | Options now routed through `ExecutionDispatcher.validate_and_dispatch` via a signal→`MultiLegStrategy` adapter that uses real chain quotes (fails closed if quotes missing) | covered by stage-order test |
| +B | `handle_signal` autopilot guardrail query used non-existent `Trade.realized_pnl`/`closed_at`/`opened_at` → raised every cycle → silently permitted | ✅ | Duplicate inline guardrail block deleted; gating is the single gate | `test_no_second_guardrail_path_in_handle_signal` |

### Follow-ups (flagged, out of batch-1 scope)
- ⬜ `paper_trader` still has its OWN dispatch path; converge it onto `order_gate` (D-2 deferred).
- ⬜ Broker-level idempotency (`dispatch_id` UNIQUE) to fully close the TOCTOU window — batch 2/4.
- ⬜ Regime size-multiplier not yet threaded into the gate's sizing (uses 1.0) — batch 3.

## Batch 2 — Broker/combo/MKT execution correctness — ✅
Real (non-simulated) orders now submit as ONE native combo; the per-leg path is
simulation-only. Already-fixed broker items confirmed and locked with tests.

| # | Issue | Status | Note | Test |
|---|-------|--------|------|------|
| 2-A | `ExecutionDispatcher.submit_atomic` legged orders separately → naked-exposure window | ✅ | `dry_run=False` routes through new `_submit_combo` → `broker.place_order` (all-or-none BAG); per-leg loop kept only for `dry_run=True` simulation | `test_real_order_uses_single_combo`, `test_combo_not_filled_no_flatten` |
| 2-B | `to_spread_order` limit price `net_premium/100` over-scaled for qty>1; sign unverified | ✅ (magnitude) / 🔶 (sign) | Now `net_premium/(100*qty)` = per-spread-per-share; sign left as-is (internally consistent w/ ibkr_client) pending live verification | `test_limit_price_per_spread_for_qty_gt_1` |
| 2-C | No order idempotency (duplicate submit) | 🔶 | In-process `_inflight` guard on `client_order_id` refuses concurrent duplicates; cross-restart `dispatch_id` UNIQUE deferred to batch 4 | `test_duplicate_inflight_refused` |
| 2-D | Combo `MKT` not honored (flatten became $0 limit); partial-as-complete; cancel-not-confirmed | ✅ | Fixed in earlier execution-safety work; `MKT` passthrough locked | `test_order_type_passthrough` |
| 2-E | No reconnect on dropped ib_insync socket | 🔶 | `disconnectedEvent` handler flips `_connected` so the 60s background loop reconnects; full mid-call reconnect not added | — |
| 2-F | Debit-spread limit aggression direction | ✅ (moot) | Gate prices options at mid via `to_spread_order`; the old `credit*aggression` path is gone | — |

NOTE: combo execution paths are logic-reviewed + unit-tested but NOT verified
against a live/paper IBKR session — confirm on paper before live.
## Batch 3 — Risk controls & data integrity — 🔶 (several items already fixed; see git log)
## Batch 4 — Fill-confirmed recording & ML integrity — 🔶 (record_fill atomicity, feature skew, look-ahead already fixed)
