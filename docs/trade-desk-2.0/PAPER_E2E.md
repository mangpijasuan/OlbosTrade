# Trade Desk 2.0 — Paper E2E Checklist

Operator walkthrough on **paper** only. Do not flip `IBKR_TRADING_MODE=live`.

## Decision: V2 default-on

**Trade Desk V2 is product-default on** (`trade_desk_v2` and desk/monitor/replay/
mobile flags in `featureFlags.ts`). Rollback: Desk Settings off or
`localStorage olbos.flags.trade_desk_v2=0`. Experimental flags
(`zero_dte_desk`, `options_flow`, etc.) stay off.

## Preconditions

- [ ] Gateway / broker connected; account shows **Paper**
- [ ] Kill switch **Clear**
- [ ] `EXECUTION_PORTFOLIO_GATE=true`, `EXECUTION_ENFORCE_PORTFOLIO_GREEKS=false`
- [ ] If `SECRET_KEY` set: paste into Risk → Operator API Key
- [ ] Trade Desk 2.0 on (default); execution mode **COPILOT**
- [ ] Prefer RTH, or temporarily `MARKET_HOURS_ONLY=false` for this smoke only

## Smoke steps

1. **Command Overview** loads queues without errors.
2. **Equity Desk** — evaluate small BUY with explicit shares (e.g. 10) → status not BLOCKED (or blocked for a known reason).
3. **Submit** composer → appears in **Copilot** pending with correct ticker.
4. **Approve** → Execution Monitor / log shows `submitted` or a clear `portfolio_gate:` / guardrail block. Confirm size matches shares (not silent 1 unless you sent 1).
5. **Manual trade** 1 share → same OMS gates apply.
6. **Engage kill switch** → approve/manual **blocked**; reset with `KILL_SWITCH_RESET_CODE`.
7. **Same-underlying identity** — with open **SPY equity**, queue/approve a **SPY options** spread (or the reverse). Duplicate guard must **not** skip as `already_open` across asset classes. Positions list must show both when both are open.
8. **Options scan** — “Queue top for approval” sends `asset_type=options` + `spread`; appears in Copilot with strikes. Thin equity-shaped options `/signal` must **400**.
9. **Scan UX** — label says queue/approval (not “Auto-execute” / “Executed”); no dead **EXECUTE LADDER**.
10. **AUTOPILOT** briefly — background `handle_signal` may execute; scan `/signal` still **queues**.
11. Force **portfolio_gate** (heat/concentration/max positions) → block reason contains `portfolio_gate:`.
12. Set `EXECUTION_PORTFOLIO_GATE=false` → one paper trade allowed → restore `true`.
13. **Orders / Execution / Replay** tabs show the event; journal optional under Research.
14. Confirm logs: only `_execute_signal` places opens; no unexpected second path.

## Pass criteria

- At least one paper fill **or** deliberate block with correct reason string
- Kill switch engage/reset works
- Composer shares preserved on approve
- Equity + options on same underlying coexist (identity / duplicate guard)
- Options scan queues with spread; incomplete options payload rejected
- No live account / live mode
## Fail → stop

Any live account mismatch, unexplained broker order, or kill switch that will not engage → stop trading, leave gate engaged, investigate before deploy.
