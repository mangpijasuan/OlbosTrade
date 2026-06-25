# OlbosQuant V3 — Hetzner Deploy Runbook

Single-command-per-line, copy-paste-safe for the Hetzner web console (which can't
paste multiline blocks and mangles some characters). Run each line on its own.

**What's shipping (branch `claude/serene-rubin-534zrm`):**
- Regime-weighted signal ranking + explicit POP gates
- Rolling-window drawdowns
- Strategy Health Monitor (auto-suspend) + Research Lab baseline bridge
- Volatility-based position sizing
- Lightweight observability (`/api/health/detail`)
- Research Lab promotion funnel (**new DB table — migration `0006`**)

The only stateful change is **one new table** (`research_experiments`). No new env
vars, no secrets, no destructive migrations. Existing data is untouched.

---

## 0. Pre-flight (5 seconds)

Confirm you're on the server, in the project root:

```
cd /opt/olbosquant
```

Snapshot the current commit so rollback is trivial:

```
git rev-parse --short HEAD
```

Write that hash down. (Rollback = `git checkout <hash>` + step 3–5.)

---

## 1. Get the V3 code

You have two choices. **Pick one.**

### Option A — merge the branch into main first (recommended, keeps `update.sh` working)

On your laptop / GitHub: merge `claude/serene-rubin-534zrm` into `main`, then on the
server just run the existing updater (it pulls main, rebuilds, restarts, migrates):

```
bash deploy/hetzner/update.sh
```

Then skip to **step 6 (verify)**. Done.

### Option B — deploy the branch directly (no merge yet)

```
git fetch origin claude/serene-rubin-534zrm
```
```
git checkout claude/serene-rubin-534zrm
```
```
git pull origin claude/serene-rubin-534zrm
```

Continue with steps 2–6 below.

---

## 2. Load prod env (needed for the DB password used by compose)

```
set -a; source backend/.env.prod; set +a
```

---

## 3. Rebuild the app images

```
docker compose -f docker-compose.hetzner.yml build --no-cache backend frontend
```

---

## 4. Restart containers

```
docker compose -f docker-compose.hetzner.yml up -d
```

Give the backend a few seconds to come up before migrating:

```
docker compose -f docker-compose.hetzner.yml ps
```

(Wait until `olbosquant-backend` shows `healthy`.)

---

## 5. Apply the database migration (creates `research_experiments`)

```
docker exec olbosquant-backend python3 -m alembic upgrade head
```

Confirm the head is `0006`:

```
docker exec olbosquant-backend python3 -m alembic current
```

You should see `0006 (head)`. Verify the table exists:

```
docker exec olbosquant-db psql -U olbosquant -d olbosquantdb -c "\dt research_experiments"
```

---

## 6. Verify V3 is live

Backend health (basic):

```
curl -fsS http://127.0.0.1:8000/health
```

V3 observability snapshot (scanner heartbeat + counters — new in V3):

```
curl -fsS http://127.0.0.1:8000/api/health/detail
```

Strategy Health Monitor (new — returns graded strategies + suspended list):

```
curl -fsS http://127.0.0.1:8000/api/strategy/health
```

Research Lab (new — should return an empty experiment list, not an error):

```
curl -fsS http://127.0.0.1:8000/api/research/lab/experiments
```

Watch the logs for a scan cycle and the new vol-sizing line:

```
docker logs olbosquant-backend -f
```

(Look for `Vol sizing:` and `Strategy health` / `Frequency controller` lines. Ctrl-C to stop.)

---

## 7. Frontend smoke test

Open the dashboard in your browser. You should now see:
- **Executive Summary**: Current DD + Rolling DD(30) tiles, a **Strategy Health**
  panel, and an engine-activity strip (scanner state + attempt/submitted/blocked).
- **Research Lab** in the left nav (flask icon) — create an experiment and step it
  through the funnel.

---

## Rollback (if anything looks wrong)

The migration is additive (a new empty table), so code rollback is safe and the
table can stay. To revert code:

```
git checkout <old-hash-from-step-0>
```
```
docker compose -f docker-compose.hetzner.yml build --no-cache backend frontend
```
```
docker compose -f docker-compose.hetzner.yml up -d
```

To also drop the table (optional, only if you want a clean revert):

```
docker exec olbosquant-backend python3 -m alembic downgrade 0005
```

---

## Notes

- **Account is PAPER (DUA086720)** — this deploy does not change broker config.
- No `.env.prod` changes required; do not re-upload secrets.
- The IBKR gateway watchdog (if installed) is unaffected.
- First `/api/strategy/health` will show `insufficient_data` for every strategy
  until ≥20 closed trades accumulate — that's expected, not an error.
