# OlbosQuant
> *From Ancient Greek ὄλβος (olbos) — blessed prosperity through disciplined, rules-based quantitative trading.*


> **Philosophy: Capital preservation first. Remove emotion. Rules are law.**

A full-stack algorithmic options trading platform with IBKR integration, psychological guardrails, AI signal scoring, and a trading journal with loss analysis.

---

## Architecture

```
options-platform/
├── backend/          Python 3.11 + FastAPI + PostgreSQL
├── frontend/         React 18 + TypeScript + Tailwind + Recharts
├── ml/               XGBoost signal scorer training pipeline
├── docker-compose.yml
└── .env.example
```

## Quick Start

### 1. Clone and configure
```bash
cp .env.example .env
# Fill in TRADIER_API_KEY and IBKR settings
```

### 2. Start services
```bash
docker compose up -d
```

### 3. Run database migrations
```bash
cd backend
alembic upgrade head
```

### 4. Verify
```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### 5. Start frontend
```bash
cd frontend
npm install
npm start
# http://localhost:3000
```

---

## Strategies

| Strategy | Direction | IV Rank | DTE | Exit |
|----------|-----------|---------|-----|------|
| Bull Put Spread | Bullish/neutral | >30 | 30–45 | 50% profit / 21 DTE / 2x loss |
| Bear Call Spread | Bearish/neutral | >30 | 30–45 | 50% profit / 21 DTE / 2x loss |
| Iron Condor | Range-bound | >40 | 30–45 | 25% profit / 21 DTE / strike breach |
| Bull Call Debit Spread | Strong bullish | <30 | 21–30 | 75% profit / 10 DTE / 50% loss |

## Guardrails

| Limit | Value | Consequence |
|-------|-------|-------------|
| Daily loss | -2% | 24h cooling off |
| Weekly loss | -5% | 3-day pause |
| Monthly loss | -10% | 30-day suspension + review |
| Consecutive losses | 3 | 48h pause |
| Daily trade cap | 3 | No more trades today |
| Capital preservation | <85% | Defense mode: credit spreads only, 50% size |

## Capital Preservation Mode

Triggers when portfolio drops below 85% of starting capital:
- Only Bull Put Spread and Bear Call Spread allowed
- Position size cut by 50%
- AI signal threshold raised: 0.65 → 0.80

## Pre-Trade Checklist

Every trade must pass ALL of these — no exceptions:
1. Guardrail check (all loss limits + cooling off)
2. Risk manager (Greeks limits + concentration)
3. AI signal score ≥ threshold
4. No earnings within 5 days
5. Daily trade cap not reached
6. Max concurrent positions not reached

## Running Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

Test coverage:
- `test_guardrails.py`      — 25 tests (all guardrail edge cases)
- `test_fill_simulator.py`  — 12 tests (all liquidity levels + commissions)
- `test_options_pricer.py`  — 25 tests (B-S within 0.01 tolerance)
- `test_data_fetcher.py`    — 9 tests (IV rank/percentile)
- `test_tradier_client.py`  — 3 tests (mocked responses)
- `test_ibkr_client.py`     — 4 tests (mocked ib_insync)

## Training the Signal Scorer

After running backtests, export trade results and train:

```bash
# 1. Run a backtest and export results
# (API: POST /api/backtest/run, then GET /api/backtest/{id}/results)

# 2. Save results to backtest_results.json
# 3. Train the model
python ml/train_signal_scorer.py backtest_results.json
```

## Pages

| Page | Key Features |
|------|-------------|
| Dashboard | Equity curve, Greeks bar, open positions, guardrail banner |
| Backtest | Strategy selector, date range, metrics, trade log |
| Paper Trade | Live positions, portfolio value, signal queue |
| Risk Monitor | Greeks gauges, daily/weekly loss meters |
| Guardrails | Loss meters, cooling off timer, event log |
| Journal | Rule Breach P&L Impact card, tag performance, mistake chart |
| Research | Strategy comparison table ranked by Sharpe |
| Strategy | Parameter display, active signals, signal score |

## Environment Variables

See `.env.example` for all configuration options.
Key variables:
- `BROKER` — `ibkr` or `tradier`
- `IBKR_PORT` — `7497` paper, `7496` live
- `STARTING_CAPITAL` — default `25000`
- `SIGNAL_SCORE_THRESHOLD` — default `0.65`

## Deployment

- Backend: Railway or Render (set all env vars, point to managed PostgreSQL)
- Frontend: Vercel or Netlify (`REACT_APP_API_URL=https://your-backend.railway.app`)

---

*Paper trade for 3 months minimum before any live capital.*
