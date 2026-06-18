# AGENTS.md

## Cursor Cloud specific instructions

OlbosQuant is a full-stack algorithmic options trading platform. Two services make up the
dev product; everything else is optional and degrades gracefully.

### Services
| Service | Dir | Dev command | Port |
|---------|-----|-------------|------|
| Backend (FastAPI) | `backend/` | `source .venv/bin/activate && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` | 8000 |
| Frontend (Vite/React) | `frontend/` | `npm run dev` | 3000 |

The Vite dev server proxies `/api` and `/health` to `http://localhost:8000`, so start the
backend first. Open the UI at `http://localhost:3000`.

### Python environment
- Python deps live in a virtualenv at `/workspace/.venv` (the update script creates it and
  installs `backend/requirements.txt`). Activate it (`source .venv/bin/activate`) before
  running the backend or `pytest`.
- The backend loads `backend/.env` from its own working directory. It is gitignored and
  optional — `app/core/config.py` has working defaults. Create it only if you need
  non-default config.

### Don't use `start.sh`
`start.sh` hardcodes a macOS path (`/Users/...`) and hard-exits if IB Gateway is not
reachable on port 4002. Run `uvicorn` and `npm run dev` directly instead.

### Optional / external dependencies (all non-blocking)
- **yfinance (internet egress)**: supplies all market-data prices, the regime classifier,
  equity scans, and backtests. Needs outbound network. The backend boots without it but
  data endpoints will be empty.
- **IBKR / IB Gateway** (port 4002): only needed for live order execution, account balance,
  and positions. The backend logs repeated "Broker reconnect failed" warnings when it is
  absent — this is expected in cloud and is not an error.
- **PostgreSQL** (`localhost:5432`) and **Redis** (`localhost:6379`): only for trade
  persistence (journal/history) and cross-process options-flow fanout. DB-backed endpoints
  fall back to defaults when absent. Start them via `docker-compose.yml` only if you need
  persistence.

### Lint / test / build
- Backend tests: `source .venv/bin/activate && cd backend && python -m pytest tests/ -q`.
  ~9 failures + 3 errors are pre-existing code/test issues (abstract `TradierClient` missing
  methods, Black-Scholes pricer tolerance boundaries, IBKR mock logic) — unrelated to env
  setup. 148+ tests pass.
- Frontend: no separate lint script. `npm run build` runs `tsc` typecheck + Vite build.

### Verifying it works (no IBKR/DB needed)
- `curl http://localhost:8000/health` → `{"status":"ok",...}`
- `curl http://localhost:8000/api/market/snapshot/SPY` → live yfinance price.
- Backtests run on yfinance history: `POST /api/backtest/run`, poll `GET /api/backtest/{id}/results`.
- UI core action that mutates state without a broker: switch the trading mode on the
  Strategy / Trade Desk page (`POST /api/mode/set`).
