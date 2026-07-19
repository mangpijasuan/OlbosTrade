# Trade Desk 2.0 — Paper E2E Checklist

Operator walkthrough on **paper** only. Do not flip `IBKR_TRADING_MODE=live`.

## Preconditions

- [ ] Gateway / broker connected; account shows **Paper**
- [ ] Kill switch **Clear**
- [ ] `EXECUTION_PORTFOLIO_GATE=true`, `EXECUTION_ENFORCE_PORTFOLIO_GREEKS=false`
- [ ] If `SECRET_KEY` set: paste into Risk → Operator API Key
- [ ] Trade Desk 2.0 flag on; execution mode **COPILOT**
- [ ] Prefer RTH, or temporarily `MARKET_HOURS_ONLY=false` for this smoke only

## Smoke steps

1. **Command Overview** loads queues without errors.
2. **Equity Desk** — evaluate small BUY with explicit shares (e.g. 10) → status not BLOCKED (or blocked for a known reason).
3. **Submit** composer → appears in **Copilot** pending with correct ticker.
4. **Approve** → Execution Monitor / log shows `submitted` or a clear `portfolio_gate:` / guardrail block. Confirm size matches shares (not silent 1 unless you sent 1).
5. **Manual trade** 1 share → same OMS gates apply.
6. **Engage kill switch** → approve/manual **blocked**; reset with `KILL_SWITCH_RESET_CODE`.
7. **Options** — prefer a full background/scanner options signal (with `spread`) for approve; do not rely on thin options scan `/signal` for fills.
8. **AUTOPILOT** briefly — background `handle_signal` may execute; scan `/signal` still **queues**.
9. Force **portfolio_gate** (heat/concentration/max positions) → block reason contains `portfolio_gate:`.
10. Set `EXECUTION_PORTFOLIO_GATE=false` → one paper trade allowed → restore `true`.
11. **Orders / Execution / Replay** tabs show the event; journal optional under Research.
12. Confirm logs: only `_execute_signal` places opens; no unexpected second path.

## Pass criteria

- At least one paper fill **or** deliberate block with correct reason string
- Kill switch engage/reset works
- Composer shares preserved on approve
- No live account / live mode

## Fail → stop

Any live account mismatch, unexplained broker order, or kill switch that will not engage → stop trading, leave gate engaged, investigate before deploy.
