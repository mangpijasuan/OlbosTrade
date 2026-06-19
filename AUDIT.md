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
| 2-B | `to_spread_order` limit price `net_premium/100` over-scaled for qty>1; sign unverified | ✅ (magnitude) / 🔶 (sign) | Now `net_premium/(100*qty)` = per-spread-per-share; wire sign now applied at the IBKR order (see Batch 2.5 C1) — verify on paper | `test_limit_price_per_spread_for_qty_gt_1` |
| 2-C | No order idempotency (duplicate submit) | 🔶 | In-process `_inflight` guard on `client_order_id` refuses concurrent duplicates; cross-restart `dispatch_id` UNIQUE deferred to batch 4 | `test_duplicate_inflight_refused` |
| 2-D | Combo `MKT` not honored (flatten became $0 limit); partial-as-complete; cancel-not-confirmed | ✅ | Fixed in earlier execution-safety work; `MKT` passthrough locked | `test_order_type_passthrough` |
| 2-E | No reconnect on dropped ib_insync socket | 🔶 | `disconnectedEvent` handler flips `_connected` so the 60s background loop reconnects; full mid-call reconnect not added | — |
| 2-F | Debit-spread limit aggression direction | ✅ (moot) | Gate prices options at mid via `to_spread_order`; the old `credit*aggression` path is gone | — |

NOTE: combo execution paths are logic-reviewed + unit-tested but NOT verified
against a live/paper IBKR session — confirm on paper before live.

## Batch 2.5 — Execution hotfixes (criticals found in re-audit) — ✅
Fixes for execution-path defects found after batches 1–2, including two
regressions introduced by the batch-1 gate.

| # | Issue | Status | Note | Test |
|---|-------|--------|------|------|
| C2 | Options over-sizing: gate's `_options_max_loss_per_contract` treated `net_credit` (dollars/contract) as per-share points → `(width − credit)*100` collapsed max-loss to the $1 floor → every options order massively over-sized (regression, batch-1 gate) | ✅ | Now `width*100 − net_credit_dollars`; same helper feeds sizing and the proposed-trade record | `test_options_max_loss_is_dollars_per_contract` |
| H1 | Gate idempotency inert: a fresh `ExecutionDispatcher` per `submit()` meant the in-process `_inflight` set never persisted, and `MultiLegStrategy.order_id` was random → duplicate guard never fired (regression) | ✅ | Dispatcher cached on the gate (rebuilt only if broker identity changes); `order_id` derived from the stable signal id | `test_dispatcher_is_cached_across_submits` |
| H2 | Manual market orders became $0 limit orders: gate hard-coded `order_type="limit"` and passed `entry_price` regardless → market intent never filled (regression) | ✅ | Gate threads `signal["order_type"]`; limit price only sent for limit orders | `test_manual_market_order_has_no_limit_price` |
| C1 | IBKR combo limit sign: `lmtPrice` sent as the positive credit; BAG combos are debit-positive for a BUY, so credit spreads quoted "willing to pay a debit" | ✅ (logic) | Wire `lmtPrice = -net` at order construction; internal `limit_price` stays signed so the retry-aggression decrement is still correct for credits and debits. **VERIFY ON PAPER** | covered by reasoning; no live test (ib_insync unavailable in CI) |
| H3 | Kill switch could not flatten equities: it built an Option BAG combo for every position, but equities use the `strike==0` sentinel → combo fails/never fills → naked exposure after engage | ✅ | Equity positions flatten via `place_equity_order(... market)`; option positions keep the combo path | `test_kill_switch_flattens_equity_via_equity_order` |
| M3 | Recording unit mismatch: gate passed `entry_credit` in dollars, but `record_exit` computes pnl `(credit − cost)*qty*100` (per-share) → P&L inflated 100× | ✅ | Gate passes `net_credit/100` (per share) at record time | covered by gate change (recording internals untouched) |
| W1 | `--workers 2` in the Dockerfile ran a duplicate APScheduler, kill-switch state and dispatcher idempotency set per process → duplicate orders | ✅ | Production now `--workers 1` until that state is externalised | — |

NOTE: C1 (combo sign) is logic-correct per IBKR's debit-positive BAG convention
but is environment-sensitive — confirm fills on the paper account before live.

## Batch 3 — Risk controls & data integrity — ✅
Several items were fixed in prior work (see git log). A re-audit surfaced the
items below; all are now resolved.

| # | Issue | Status | Note | Test |
|---|-------|--------|------|------|
| 3-A | Equity P&L corrupted: `record_exit` always applied the ×100 options multiplier (and credit-spread sign) to equity trades — `instrument_type` was never set on write, so every row stayed the `"option"` default → equity P&L inflated ~100× and sign-inverted, poisoning the daily/weekly/monthly loss windows the gate reads | ✅ | `record_fill` now sets `instrument_type`; `record_exit` branches via testable `_gross_pnl` → equity uses `(exit−entry)×shares` (no ×100). LONG-only (short-equity sign needs a stored side — flagged) | `test_equity_long_profit_no_100x`, `test_equity_long_loss_sign`, `test_credit_spread_keeps_100x`, `test_debit_spread_sign_inverted` |
| 3-B | Combo retry abort `limit_price <= 0` tripped immediately for debit spreads (negative limit) → debits never retried on timeout | ✅ | Abort is now credit-only (`is_credit and limit_price <= 0`); the decrement is more-marketable for both signs | covered by reasoning (ib_insync unavailable in CI) |
| 3-C | EmotionGuard inert: `record_trade_result` was never called → tilt/revenge detection never updated (consecutive-loss still enforced via the DB guardrail, so this was the tilt layer only) | ✅ | `EmotionGuard` is now a process-global singleton shared by every `UnifiedRiskEngine` and by `TradeRecorder.record_exit`, which records win/loss + notional at the single close path. The gate's `check()` consults the same state. In-memory only (resets on restart; DB consecutive-loss guardrail still spans restarts) | `test_four_consecutive_losses_pauses_engine`, `test_emotion_guard_is_shared_singleton`, `test_a_win_resets_consecutive_losses` |
| 3-D | Cooling-off not enforced at the gate: `_read_portfolio_state` never populated `cooling_off_until`, so the gate let trades through as soon as the *triggering* metric cleared (e.g. at the daily P&L reset), short-circuiting the suspension window | ✅ | The store already existed (`portfolio_snapshots.cooling_off_until`, written by the autopilot loop each cycle). The gate now reads the latest snapshot's `cooling_off_until` into `PortfolioState`, so `check_all` branch #1 enforces the full window | `test_future_cooling_off_blocks`, `test_expired_cooling_off_allows` |
| 3-E | Concentration/Greeks never bound: the check ran BEFORE sizing and scored per-unit `max_loss_dollars` (per-share for equity, per-contract for options) against the whole portfolio | ✅ | Risk `check()` moved to after sizing (Stage 3.5); `approve_trade` takes `position_quantity` and scales single-underlying / sector / delta / vega by the sized count → scored against the TOTAL position | `test_quantity_scaled_exposure_breaches_concentration`, `test_single_unit_within_concentration`, `test_default_quantity_is_one` |
## Batch 4 — Fill-confirmed recording & ML integrity — 🔶
Recording is correctly fill-gated (options record only on `DispatchStatus.FILLED`;
equity after the broker order returns) and atomic (Trade+JournalEntry in one
transaction; `record_exit` row-locks `status="open"` against double-close).
Training is sound: point-in-time IV/RV (no look-ahead), `TimeSeriesSplit(gap)`,
`df[FEATURE_NAMES]` order-safe, serve/train `FEATURE_NAMES` aligned. The re-audit
found the items below.

| # | Issue | Status | Note | Test |
|---|-------|--------|------|------|
| 4-A | `record_fill` accepted `dispatch_id` but **never persisted it** (no such column) → no cross-restart idempotency: the in-process `_inflight` guard dies on restart, so a retried/second close path could record the same fill twice (duplicate open position) | ✅ | Added `trades.dispatch_id` (nullable, UNIQUE, indexed) + migration `0006`; `record_fill` normalises empty→NULL, pre-checks by `dispatch_id` (returns the existing trade_id), and treats a UNIQUE race as a duplicate. **VERIFY migration on Postgres** (no DB test harness — models use PG `UUID`) | logic-reviewed; idempotency path unit-tested indirectly |
| 4-B | Train/serve skew on `earnings_days_away`: training caps at 60 (`ml/features.py`), but live `SignalFeatures` passed raw values (e.g. 999 for ETFs) — the model uses this feature (`EXPECTED_POSITIVE_SHAP`), so inference saw values that never occurred in training | ✅ | `SignalFeatures.__post_init__` now caps at 60, matching training exactly | `test_earnings_days_away_capped_at_60_for_etf`, `..._under_cap_unchanged`, `..._exactly_60_unchanged`, `test_to_array_uses_capped_value` |
| 4-C | Train/serve skew on `vix_term_slope`: training computes real VIX3M/VIX; live `SignalFeatures` hard-defaults to 1.05 → the model is fed a constant for a feature it was trained on (also in `EXPECTED_POSITIVE_SHAP`) | ⬜ | Needs a live VIX3M quote at serve time (data-feed dependent) — flagged. Until wired, a retrained model that depends on this feature will be served a constant | — |
| 4-D | Flow features (`flow_sentiment_score`, `flow_large_sweep_bullish_count`) never wired into live `SignalFeatures` despite the documented source `regime_classifier.compute_flow_features('SPY')` → defaults 0.5/0 at serve. No skew **today** (training backfills the same defaults for pre-feed trades), but latent once live flow accumulates in the training set | ⬜ | Wire `compute_flow_features` into the serve path when the flow feed is trusted — flagged | — |

NOTE: 4-A's migration and unique-constraint behaviour are logic-correct but
unverified against Postgres (CI has no DB; ORM uses PG-specific `UUID`). Confirm
the migration applies and the dedup fires on the paper database before live.
