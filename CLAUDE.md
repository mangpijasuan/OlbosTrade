# OlbosTrade — Claude Code Project Brief

> Last updated: 2026-08-23  
> Read this before making any changes to the codebase.

---

## What This Project Is

OlbosTrade is a single-operator automated trading platform.  
Primary stack: **FastAPI backend** (Python 3.11) · **React/Vite frontend** (TypeScript) · **PostgreSQL** · Docker Compose.  
Brokers: **IBKR** (ib_insync) and **Alpaca** behind a `broker_interface.py` abstraction.

---

## Execution Architecture (critical — read before touching order code)

**There is exactly one order pipeline:** `_execute_signal` in `backend/app/api/routes/trade_desk.py`.

Every order entry point (AUTOPILOT background scanner, manual queue approval, Trade Desk V2) **must** route through `_execute_signal`. Never bypass it.

Pipeline stages (in order, all required):
1. Kill switch check
2. Market hours check
3. Frequency controller (non-manual)
4. Strategy health (non-manual)
5. GuardrailEngine risk check (fail-closed — DB error = refused)
6. Portfolio gate — concentration / max positions / heat
7. Duplicate guard — keyed on `(underlying, asset_class)` via `trade_identity.py`
8. Sizing
9. Broker submission + fill recording

The scan panels (`POST /api/equity/scan`, `POST /api/options/scan`) **cannot reach AUTOPILOT** — they queue for approval only (`submit_scan_signal` autopilot branch is disabled pending tests).

---

## Risk Constants — Single Source of Truth

Greeks limits live in **one file only**:

```
backend/app/services/risk_limits.py
```

- `MAX_PORTFOLIO_DELTA = 0.30`
- `MAX_PORTFOLIO_VEGA  = 0.15`

Both `risk_manager.py` and `portfolio_greeks.py` import from `risk_limits.py`.  
**Do not hardcode these values anywhere else.** If you change a limit, change it in `risk_limits.py` only.

---

## Position Identity — Key on (underlying, asset_class)

`backend/app/services/trade_identity.py` provides:
- `asset_class_from_trade(trade)` → `"equity"` or `"options"`
- `asset_class_from_signal(signal)` → `"equity"` or `"options"`
- `position_identity_key(underlying, asset_class)` → `(str, str)` tuple

**Always use these helpers** when looking up or comparing open positions.  
Keying on bare `underlying` string will false-block SPY equity when a SPY option spread is open, and vice versa.

---

## ML Signal Scorer

`backend/app/services/signal_scorer.py` — XGBoost regressor (predicts return-on-risk).  
**No trained model exists on disk yet.** The scorer runs its `_heuristic_score()` fallback.  
To train: `ml/train_signal_scorer.py` (requires labeled backtest data).  
Until a model is trained, treat signal scores as heuristic, not ML-derived.

---

## Open Architecture Items (as of 2026-08-23)

| Sev | Item | Location |
|-----|------|----------|
| P1 | Kill-switch *engage* unauthenticated at FastAPI (by design; nginx handles it) | `trade_desk.py` |
| P2 | ML signal scorer running heuristic fallback — no trained model on disk | `signal_scorer.py`, `ml/train_signal_scorer.py` |
| P2 | No broker-event streaming (everything polls) — hard blocker for live capital | `ibkr_client.py`, `ibkr_coordinator.py` |
| P2 | Margin / buying power not surfaced operationally | `broker_interface.py` |
| P3 | Vestigial `POST /api/equity/signals/{id}/approve` endpoint (dead) | `equity.py:107` |
| P3 | `TRADING_POLICY.md:34-35` says "SPY-only options" — false since QQQ options shipped | `TRADING_POLICY.md` |
| P3 | Frontend single bundle 477 kB / no code splitting | `frontend/` |

**Already fixed (do not re-open):**
- Position identity keyed on `(underlying, asset_class)` — `trade_identity.py`
- Duplicate guard asset-type aware — `trade_desk.py:1022`
- Delta/vega constants unified in `risk_limits.py`
- Execution mode persisted to DB (not `/tmp`)
- Capital base single source: `account_state.py::get_account_value()`
- API-key auth on all mutate routes (`deps.py::require_api_key`)

---

## Build / Test

```bash
# Backend tests
cd backend && pytest

# Frontend type check
cd frontend && npx tsc --noEmit

# Frontend tests
cd frontend && npm run test

# Frontend production build
cd frontend && npm run build
```

Run `gh run list --branch main --limit 1` after every push to `main`.  
A red `main` that nobody checks is how a regression ships unnoticed.

---

## Infrastructure

- `docker-compose.yml` — local dev (backend :8001, frontend :3001, postgres :5435, IB Gateway :4002/:5900)
- `docker-compose.prod.yml` — production (nginx, no reload)
- `docker-compose.hetzner.yml` — Hetzner VPS variant
- IB Gateway runs via `ghcr.io/gnzsnz/ib-gateway:stable`; paper port 4002, live port 4001
