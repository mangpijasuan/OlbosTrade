# OlbosTrade Security & Correctness Audit

## Batch 1 — Single Fail-Closed Order Pipeline

**Goal:** Every order must flow through exactly ONE pipeline:
kill switch → guardrail risk → sizing → broker → fill-confirmed recording.
No path may skip a stage. DB read failure = refuse trade (fail closed).

| # | Issue | Resolution | Test |
|---|-------|-----------|------|
| 1 | `_execute_signal()` skipped UnifiedRiskEngine/guardrails — went kill switch → broker | Rewrote `_execute_signal` as the single gate; stages 1-5 enforced for all callers | `test_signal_blocked_on_guardrail_breach` |
| 2 | `manual_trade` endpoint bypassed all guardrails except kill switch | Removed inline broker call; `manual_trade` now builds signal dict and calls `_execute_signal` | `test_manual_order_blocked_on_guardrail_breach` |
| 3 | Copilot `approve_signal()` → `_execute_signal()` was unguarded | Fixed by #1 — `approve_signal` already called `_execute_signal`; gate now inside it | `test_copilot_approved_blocked_on_guardrail_breach` |
| 4 | `handle_signal()` had its own inline duplicate guardrail block | Deleted the inline block; autopilot path calls `_execute_signal` like all other paths | `test_no_second_guardrail_block_in_handle_signal`, `test_handle_signal_autopilot_delegates_to_execute_signal` |
| 5a | Guardrail DB read `except Exception: pass` — defaulted to zeros (fail open) | Replaced with `_fetch_portfolio_state()` that raises `RiskGateError` on any DB failure | `test_db_read_failure_is_fail_closed` |
| 5b | `handle_signal` queried `Trade.realized_pnl` / `Trade.closed_at` (non-existent columns) — raised every cycle, was swallowed, always permitted | Fixed columns to `Trade.pnl` / `Trade.exit_date` / `Trade.status == "closed"` in `_fetch_portfolio_state` | `test_wrong_column_exception_is_fail_closed`, `test_fetch_portfolio_state_uses_correct_columns` |
| 6 | Sizing floor `max(..., 1)` in `paper_trader.py` forced at least 1 contract | Removed floor; `effective_contracts = int(...)` now allows 0; zero triggers `skipped_zero_size` | `test_calculate_position_size_returns_zero_for_tiny_budget`, `test_zero_contracts_skipped_in_execute_signal`, `test_zero_shares_skipped_in_execute_signal` |

---

## Batch 2 — Broker/Combo/MKT Execution Correctness ✅ DONE

Merged as PR #4 (`087b2ba`). Tests: `tests/test_ibkr_execution.py`.

---

## Batch 3 — Risk Controls & Data Integrity

**Goal:** Close risk control gaps: capital preservation actually gates trades, mode risk % reaches sizing, reconciliation catches doubled positions, EmotionGuard survives restarts, Decimal precision in guardrail math.

| # | Issue | Resolution | Test |
|---|-------|-----------|------|
| 1 | Sizing floor `max(..., 1)` in paper_trader forced ≥1 contract | Removed in Batch 1; `effective_contracts = int(...)` allows 0 | `test_risk_manager_returns_zero_when_budget_exhausted`, `test_sizing_floor_removed_from_risk_manager` |
| 2 | Capital preservation computed but never gated strategies in manual/copilot path; main.py snapshot overwrote mode with user-selected mode | `_execute_signal` now calls `is_strategy_allowed()` after guardrail check; removed main.py override — snapshot returns `status.trading_mode` | `test_capital_preservation_blocks_iron_condor`, `test_execute_signal_blocks_iron_condor_in_preservation`, `test_execute_signal_allows_credit_spread_in_preservation` |
| 3 | `size_position()` hardcoded `risk_pct=0.02/0.03/0.015` — ignored active trading mode | Added `_active_risk_pct()` helper; all 4 `size_position` methods now read from `trading_mode_manager.current.config.risk_per_trade_pct` | `test_active_risk_pct_reads_from_trading_mode`, `test_size_position_uses_active_mode_risk` |
| 4 | Reconciliation matched on `underlying` string set only — doubled position looked clean | Quantity-aware matching: groups by underlying, sums quantities, raises `ReconciliationError` on mismatch | `test_reconciliation_flags_doubled_position`, `test_reconciliation_clean_when_quantities_match` |
| 5 | `EmotionGuard` state in-memory only — consecutive_losses and paused_until reset on restart; inconsistent loss definition | Added `rehydrate_from_db()` and `_persist_to_db()` to `EmotionGuard`; `record_trade_result` is now async and persists after each trade; loss defined as `pnl < 0` (strictly negative) | `test_emotion_guard_rehydrates_consecutive_losses`, `test_emotion_guard_rehydrates_paused_until`, `test_emotion_guard_persists_after_loss` |
| 6 | `PortfolioState` PnL fields were `float` — guardrail comparisons lost monetary precision | `PortfolioState.daily/weekly/monthly_pnl` changed to `Decimal`; `check_all()` uses `Decimal` arithmetic; all callers return `Decimal(str(...))` | `test_portfolio_state_accepts_decimal_pnl`, `test_guardrail_check_uses_decimal_arithmetic` |

---

## Batch 4 — Fill-Confirmed Recording & ML Integrity

**Goal:** Every broker fill must land in the DB exactly once; DB failures after fills emit CRITICAL alerts; journal stubs don't corrupt analytics with synthetic confidence values; P&L percentages scale with configured capital; iv_rank degenerate convention is consistent.

| # | Issue | Resolution | Test |
|---|-------|-----------|------|
| 1 | `dispatch_id` accepted by `record_fill` but never stored on Trade row — no way to detect duplicate fills | Added `dispatch_id: Mapped[Optional[str]]` with `unique=True` to Trade model; migration 0005 adds column + UNIQUE constraint; `record_fill` stores it and checks for existing record before inserting | `test_dispatch_id_column_exists_on_trade_model`, `test_dispatch_id_in_record_fill_constructor`, `test_record_fill_idempotent_on_duplicate_dispatch_id` |
| 2 | `record_fill` DB failure swallowed with `logger.error` only — broker position untracked in DB with no CRITICAL alert | Changed except block to `logger.critical(...)` including `dispatch_id` so oncall can cross-reference broker fill | `test_record_fill_emits_critical_on_db_failure`, `test_record_fill_uses_critical_not_only_error` |
| 3 | `JournalEntry.confidence_level=3` hardcoded in every auto-created stub — pollutes confidence vs. outcome analytics with synthetic data | Changed to `confidence_level=None`; trader fills it in via Journal UI or leaves blank | `test_confidence_level_is_none_in_record_fill` |
| 4 | `pnl_pct = pnl / 25000.0` hardcoded — wrong for any other starting capital | Changed to `pnl / settings.starting_capital`; guard against zero division | `test_pnl_pct_uses_settings_not_hardcoded`, `test_pnl_pct_scales_with_starting_capital` |
| 5 | `IVSurfaceEngine._compute_iv_rank` returned `50.0` for degenerate case (hi==lo) — inconsistent with `market_data.py` returning `None`→0; biased ML training data | Changed degenerate return to `0.0` (lowest rank) across both modules | `test_iv_rank_degenerate_returns_zero`, `test_iv_rank_degenerate_not_50` |
