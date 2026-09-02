# ML Intelligence Layer — assessment, label investigation, and plumbing fixes (2026-08-28)

## Context

The operator supplied an "ALPHA EDGE ML INTELLIGENCE LAYER" spec (27 sections:
feature pipeline, multi-horizon XGBoost models, calibration, Expected R, SHAP,
model registry/promotion/drift, no-trade classifier, Capital Rotation and Risk
Engine integration) and asked for an assessment before implementation, per its
own §27 "inspect the existing codebase first."

**Verdict: architecture sound, data ~50x short. No models built.**

The safety architecture is genuinely good — ML advisory-only with the Risk
Engine authoritative, mandatory calibration, walk-forward with no shuffling,
promotion gates, drift → autopilot downgrade, and §25's "never manufacture
statistics." Several of those directly address bugs fixed earlier this week.
The blocker is sample size, not design.

## What the data actually is (measured, not estimated)

- `signal_outcomes`: ~70.8k rows, but only ~1,568 distinct
  (ticker, action, day) — the scanner re-records the same signal every tick,
  ~45x duplication. Effective sample ≈ 1,568 signal-days across **14 market
  days**, and those days are themselves the clustering unit.
- **44 closed trades total, all equity. Zero options. Zero 0DTE.** The spec's
  §6 wants separate SCALP/INTRADAY/SWING/0DTE models; three have no examples.
- `trades.regime` populated on **0 of 98 rows**, despite Phase 2B wiring it.

## The label investigation

The resolved label split looked broken: 5,407 `stop_hit` vs 388 `target_hit`
(93/7), with 64,902 pending. Root-caused to three compounding causes, only one
of which was a defect.

**Defect (fixed, commit `381b6d4`, deployed):** `check_pending_outcomes()`
opened a session AND a transaction per row, and stamped `checked_at` on every
pending row each pass — ~65k transactions against a 120s scheduler budget. It
was killed mid-pass every run (`Scheduler task 'signal_outcomes' timed out
after 120s` on consecutive runs), and only **32 of 102 tickers** had ever
received a single label; the other 70 had none. The damage was not slowness —
a truncated pass leaves a labelled subset selected by DB iteration order and
by where the timeout landed, and it reads exactly like real data.

Fixed with batched writes (same-value `checked_at` collapses to one UPDATE per
chunk; resolutions go out as one executemany), oldest-backlog-first ticker
ordering so a short pass drains the most-starved tickers, and an inner deadline
(240s) below the guard (600s) so a pass that cannot finish ends cleanly at a
ticker boundary and reports `truncated`. Partial coverage now logs a WARNING
naming the shortfall. Runs in ~70-80s.

**Not defects — accepted properties:**
- *Censoring.* `expired` had never once fired: max bars elapsed ~9 against a
  20-bar horizon, so a third of the label space did not exist.
- *Geometry.* stop = 2xATR, target = 4xATR, universe ATR 4.46% of price → the
  target demands an ~18% move (MNST's sits 60.9% away) inside 20 bars.
  Stopped-out signals reached average MFE of only +1.89% — not near misses.

**Backfill applied** (`scripts/backfill_signal_outcomes.py`, dry-run by
default, imports the app's own `_resolve_one` so no unreviewed code decides a
label): 3,479 rows written, 101/101 tickers processed in 79s. Result —
label coverage 32/102 → **52/102 tickers**, target share of decided outcomes
6.7% → **7.0%**, total resolved 9,274 of 70,798 (13.1%), still 86.9% pending.

**Correction worth recording:** fixing the truncation moved *coverage*
enormously and the *ratio* almost not at all. The lopsided split was censoring
and geometry, not the bug found first. "Processing coverage 101/101" and
"label coverage 52/102" are different numbers and were briefly conflated.

## Model deployment gap (commit `5baf18e`, deployed)

`ml/model_registry/signal_scorer_v1.pkl` appeared committed but absent from the
container. Actually two directories: a stale repo-root `ml/` **fork** (differing
`features.py`/`train_signal_scorer.py`, a 75KB June pkl nothing loads, and a
119-byte empty notebook stub) and the real `backend/ml/` (482KB, Aug 14) that
`backtester.py`'s `from ml.features import ...` resolves to. Build context is
`./backend`; `.gitignore` excluded `*.pkl` under exactly that path. No model
could ever reach the image.

**The model was deliberately NOT shipped.** Loaded in the production container
to check: unpickles clean, SHAP builds, 24 days old — and its own recorded
metrics are **r2 = -0.173** and **directional_accuracy = 0.5068** on n_val=442
(95% CI ≈ [46.0%, 55.4%]). Negative r2 predicts worse than the mean. It gates
trade approvals at a 0.12 threshold, so shipping it would have replaced honest
heuristic scoring with a model that has no skill. The deployment gap was
accidentally protecting the desk. `n_train=1767` also corroborates the
data-scarcity finding: someone already tried XGBoost on this data.

Four fixes: removed the dead repo-root `ml/`; bind-mounted
`backend/ml/model_registry` read-only into the container so models live on the
host and take effect on restart without a rebuild or a binary in git history;
guarded `pickle.load` (it was unwrapped — a bad artifact raised inside
`__init__` and took down every caller, instead of using the correct heuristic
fallback that already existed); and added `SignalScorer.status()`, surfaced at
`/api/health/detail` as `signal_model`, reporting scoring_mode, path,
path_exists, last_trained, the validation metrics verbatim (bad ones included),
and a `usable` verdict — loading is not the same as working.

Live-verified: `scoring_mode: "heuristic"`, `loaded: false`, `usable: false`,
mount `/opt/olbostrade/backend/ml/model_registry -> /app/ml/model_registry
(rw=false)`.

## Decisions

- **Keep the 20-bar horizon** (operator decision, 2026-08-28). The
  stop-weighted label distribution is therefore an accepted property, not a
  symptom — do not re-investigate the resolver on the strength of a low target
  share. Any model trained on these labels inherits a heavily imbalanced target
  and needs class weighting or an Expected-R objective rather than raw accuracy.
- **Do not train models yet.** Revisit when there are >= 6 months of resolved,
  uncensored labels and non-zero options history. `expired` first fires at 20
  trading bars, so the label space is complete for the first time around
  **mid-September 2026**.

## Retracted theory — do not revisit

The ATR feeding the stop/target geometry is **not** corrupted. MNST at 15.22%
daily ATR looked impossible; checked against 11 years of independently-fetched
adjusted bars — universe mean 4.37% vs the DB's 4.46%, 1.0x on six of seven
spot-checked tickers, and MNST is *higher* in clean data (24.66%). The
watchlist is genuinely that volatile.

## Still open

- Whether the deterministic Alpha Edge beats a coin flip out-of-sample has
  never been measured. The spec's §11 fusion assumes it is worth fusing with;
  worth measuring before weighting ML against it.
- Options flow / positioning features (§4) have no data source — they need a
  paid feed.
- The account runs on `reqMarketDataType(4)` (delayed 15-min), which undermines
  §4's spread/liquidity/slippage features and §20's real-time-vs-historical
  consistency requirement at the source.
