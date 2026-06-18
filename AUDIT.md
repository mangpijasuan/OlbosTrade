# AUDIT

## Batch 1 — single fail-closed order pipeline

- [x] `_execute_signal` bypassed unified risk / sizing / dispatcher.
  - Resolved by making `_execute_signal` the shared fail-closed gate for signal, autopilot, copilot approval, and manual entry paths.
  - Covered by: `test_clean_order_calls_stages_in_order`.

- [x] Manual trade bypassed guardrails except kill switch.
  - Resolved by routing `manual_trade` through `_execute_signal`.
  - Covered by: `test_manual_order_with_risk_breach_is_rejected`.

- [x] COPILOT approval was a separate order-placing path.
  - Resolved by keeping `approve_signal` on `_execute_signal`, now the single gate.
  - Covered by: `test_copilot_approved_order_with_risk_breach_is_rejected`.

- [x] AUTOPILOT had a duplicated inline guardrail block in `handle_signal`.
  - Resolved by deleting the inline guardrail path; AUTOPILOT now delegates to `_execute_signal`.
  - Covered by: `test_handle_signal_has_no_second_guardrail_path`.

- [x] Guardrail DB read failures failed open with zero P&L / zero trade counts.
  - Resolved by having gate risk-state reads raise and block with `risk_state_unavailable`; guardrail status endpoint now returns fail-closed state on DB error.
  - Covered by: `test_guardrail_db_failure_blocks_order`.

- [x] Nonexistent `Trade.realized_pnl` / `Trade.closed_at` query path had allowed fail-open behavior.
  - Resolved by removing the duplicated AUTOPILOT guardrail query entirely; the single gate reads current `Trade.pnl` / `Trade.exit_date` / `Trade.status` fields and blocks on query failure.
  - Covered by: `test_guardrail_db_failure_blocks_order` and `test_handle_signal_has_no_second_guardrail_path`.

- [x] Zero-size results were floored up to one contract.
  - Resolved by allowing `RiskManager.calculate_position_size` and `paper_trader` effective sizing to return zero and skip.
  - Covered by: `test_zero_size_skips_without_dispatch`.
