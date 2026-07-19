# Trade Desk 2.0 — Integration Audit (Claude Code stage)

**Date:** 2026-07-19  
**Scope:** Post Phases B–F + Step 8. Readiness for paper E2E. **No live deploy.**

## Verdict

**Ready for paper E2E** behind the single OMS gate `_execute_signal`.  
Scan→approve sizing gap for equity **shares** hardened in this stage (see CHANGELOG).

---

## 1. Single OMS gate

| Path | Reaches broker open? |
|------|----------------------|
| `approve_signal` → `_execute_signal` | Yes |
| `manual_trade` → `_execute_signal` | Yes |
| `handle_signal` (AUTOPILOT background) → `_execute_signal` | Yes |
| `POST /api/trade-desk/signal` (scan / Equity composer) | **Queue only** (all modes) |
| Kill switch engage | Flatten only (not new entries) |
| `POST /api/equity/signals/{id}/approve` | Metadata only — no broker |

**Confirmed:** no second live open-order path.

---

## 2. Step 8 portfolio gate

| Item | Status |
|------|--------|
| Stage 2b in `_execute_signal` | On |
| Checks | Max positions, underlying ≤25%, sector ≤40% hard, heat >50% |
| Greeks delta/vega | **Off** (`EXECUTION_ENFORCE_PORTFOLIO_GREEKS=false`) |
| DB load failure | Fail-open for this gate only |
| Rollback | `EXECUTION_PORTFOLIO_GATE=false` |

---

## 3. Feature flag defaults

| Flag | Default |
|------|---------|
| `trade_desk_v2` and desk/monitor/replay/mobile | **off (opt-in)** |
| `zero_dte_desk`, `options_flow`, alpha/probabilistic | **off** |

Enable V2: Desk Settings checkbox, or `localStorage olbos.flags.trade_desk_v2=1`, or `VITE_TRADE_DESK_V2=1`.
Legacy desk is the default until then.

---

## 4. Security

| Control | Status |
|---------|--------|
| Mutate routes + `SECRET_KEY` / `X-Api-Key` | On when key set; skipped if empty (local) |
| Kill reset | `KILL_SWITCH_RESET_CODE`; empty = reset disabled |
| Hardcoded frontend reset string | Removed |
| Prod must set | `SECRET_KEY`, `KILL_SWITCH_RESET_CODE` |

---

## 5. Remaining risks (accepted for paper)

| Sev | Item |
|-----|------|
| Med | Options scan `/signal` is equity-shaped — use background options signals for options fills |
| Med | Scan autopilot still queues (by design) — do not expect scan→auto-fill |
| Med | Portfolio gate / duplicate check fail-open on some DB errors |
| Low | Kill engage unauthenticated at FastAPI (rely on nginx + hold-to-confirm) |

---

## 6. Related docs

- Paper walkthrough: [`PAPER_E2E.md`](./PAPER_E2E.md)
- Deploy prep (gate only): [`DEPLOY_PREP.md`](./DEPLOY_PREP.md)
- Plan: [`PLAN.md`](./PLAN.md)
