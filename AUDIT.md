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

## Batch 2 — Broker/combo/MKT execution correctness — ⬜ pending
## Batch 3 — Risk controls & data integrity — 🔶 (several items already fixed; see git log)
## Batch 4 — Fill-confirmed recording & ML integrity — 🔶 (record_fill atomicity, feature skew, look-ahead already fixed)
