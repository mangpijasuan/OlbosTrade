# Mobile Trade Ideas — Data Availability Audit

Every field the mobile-first spec displays, mapped to a real source in this
codebase. Purpose: decide what can be built honestly before any screen is
designed around a value that will render `NO DATA` forever.

Verified by direct inspection on 2026-08-29, not from memory.
Corrected 2026-08-30 — see §2, which named a taxonomy that does not exist.

Legend — **A** available today · **D** derivable from what exists · **X** no source

---

## Correction to an earlier assessment

I told the operator that `EST. POP` could not be produced honestly. **That was
wrong.** `options_intelligence.py:94` computes a real Black-Scholes
probability of profit — `norm.cdf(d2_be)`, risk-neutral, derived analytically
from IV, strike, DTE and breakeven. It is a standard options metric and the
spec's §8 tooltip describes it accurately.

The distinction that matters: it is a **risk-neutral analytic** probability,
not a calibrated empirical one. It says what Black-Scholes implies given the
market's own IV. It does *not* say what this desk's signals historically
achieve — and those differ sharply (only 7.0% of resolved equity signals ever
reached target). Label it as the former and it is honest; imply the latter and
it is not.

**POP is options-only.** Equity signals carry no POP field of any kind.

---

## 1. Live intelligence ticker (§5)

| Field | Status | Source |
|---|---|---|
| Symbol | A | any signal |
| Direction B/S | D | `orderflow_score` sign |
| **Dollar flow `$568.8K`** | **X** | no source |
| **Venue tag `SPLIT`** | **X** | no source |
| Signal strength % | D | `abs(orderflow_score)` |
| Timestamp | A | `generated_at` |

`orderflow_engine.py` derives a −1..+1 bid/ask imbalance score from the
broker's latest quote. It cannot produce a dollar figure or a venue. There is
no dark-pool or block feed.

**Verdict: rebuild the ticker around what exists** — symbol, direction,
imbalance strength, time. Dropping the dollar amounts is the only honest
option short of buying a flow feed.

## 2. Strategy categories (§6)

**Corrected 2026-08-30.** The first pass of this section said "Code contains
`directional` and `spread` only" and recommended shipping those as two real
tabs. That was wrong, and it was wrong in the exact way this document exists
to prevent — it named a taxonomy that does not exist in the data.

`directional` appears nowhere as a category. Its only occurrences are prose:
`"directional bias"` in an `options_decision_engine` docstring, and
`directional_accuracy` as a model metric in `signal_scorer`. `spread` is a
field *name* on options signals, not a category value. **There is no category
field on a signal at all.**

Caught while wiring the tabs — the recommendation was followed, and the data
to follow it with was not there.

What actually discriminates a signal:

| Field | Values | Populated |
|---|---|---|
| `asset_type` | `equity`, `options` | yes — **and already a UI toggle** |
| `strategy` | `equity`, `bull_put_spread`, `bear_call_spread`, `iron_condor`, `bull_call_debit_spread` | yes |
| `action` | `BUY`, `SELL` | yes |

Note `iron_condor` is dead code — `main.py`'s scan loop skips it — so the live
options vocabulary is three strategies, all of them verticals.

**Verdict: no category tab row.** `asset_type` is the only real axis and it
already has the OPTIONS / EQUITIES toggle. `strategy` is a card field, not a
navigation axis, and grouping by it would render one group given the single
options trade in history (§7). A second tab row on a 375px screen has to earn
its space; this one cannot.

Revisit only if a genuine category field is added to the signal schema —
which is a backend modelling decision, not a mobile task.

## 3. Trade Idea card (§7)

**Options — nearly complete.** `strategy, option_type, short_strike,
long_strike, expiration, dte, net_credit, max_loss, breakeven, pop,
kelly_fraction, iv_rank, confidence, signal_score, regime, quantity,
bid_ask_width_pct, open_interest, gamma, evidence, top_positive_factors,
top_negative_factors`.

Missing: `target` and `stop` as explicit prices (exit rules live in
`StrategyExitParams` as multiples, not levels) and `status`.

**Equity — thinner.** Signal: `ticker, action, confidence, signal_score,
orderflow_score, iv_overlay_boost, earnings_gated, reasons, regime,
indicators, opportunity_score, routable`. Plan: `entry_price, stop_price,
target_price, shares, position_size, risk_dollars, risk_reward,
target_move_pct`.

Has entry/stop/target — which options lacks. Has **no POP**.

**Verdict: the two asset classes need different cards.** A single card
forcing both into one shape will show blanks in half its slots either way.

## 4. Thesis and Agent Consensus (§10, §11)

| Element | Status |
|---|---|
| "Why OLBOS likes it" | A — `reasons[]` (equity), `evidence` + SHAP factors (options) |
| Regime | A — `regime` on both |
| IV | A (options) / partial (equity `iv_overlay_boost`) |
| Flow | D — `orderflow_score` |
| Catalyst | partial — `earnings_gated` is a boolean, not a catalyst object |
| **Technical Agent** | D — `signal_score` |
| **Options Flow Agent** | D — `orderflow_score` |
| **Volatility Agent** | D — `iv_rank` / `iv_overlay_boost` |
| **Earnings Agent** | X — no such module |
| **Regime Agent** | A — `regime_classifier` |
| Invalidation (§28) | X — no field anywhere |

There are no "agents". There are scoring functions. Three of the five named
can be honestly presented as *signal components*; "Earnings Agent" cannot.

**Verdict: rename to Signal Components and show the three that exist.**
Calling a heuristic sum an "Agent" implies an autonomy the code does not have.

## 5. Trade Plan, Risk Preview, Pre-Trade Gate (§12, §14, §20)

| Field | Status |
|---|---|
| Entry / stop / target / contracts | A (equity) · D (options) |
| Max loss | A — `max_loss` (options), `risk_dollars` (equity) |
| Max profit | A (options) · D (equity) |
| Risk : reward | A — `risk_reward` |
| Buying power | A — `get_account_summary()` |
| **Portfolio heat** | A — fixed 2026-08-29, see below |
| Single-name exposure | A — `portfolio_engine` concentration |
| Daily risk used | A — `guardrails` |
| 10 pre-trade checks | A — `_execute_signal` Stages 1–5 already implement 8 of 10 |

**Portfolio heat was the one landmine — fixed 2026-08-29 (commit `8afa80c`).**
`position_risk_dollars` defined equity risk as `entry × shares`, full notional,
and heat plus both concentration checks consumed it as risk-at-stake. It read
**94.06%** for a book that was simply invested, and the blocks were real: 179
concentration blocks in 21 days plus 4 heat blocks at 87–89%.

It now measures `|entry − stop| × shares` using the stop already stored in
`long_strike`. Live reading is **14.99%**, `heat_status: ok`, no concentration
flags. It read 43.53% immediately after that first fix, because two of three
positions were adopted by the reconciler and carry `entry == stop`
placeholders; `stop_backfill` (`5980e4c`, scheduled in `80d85c6`) then
recovered their real stops from the live order book, and
`unstopped_position_count` is now 0.

**Mobile can display heat, but must display `heat_overstated` with it.** A bare
percentage that is sometimes a measurement and sometimes an upper bound is the
same category of dishonesty as a fabricated POP.

**Two adjacent defects remain open:**
1. ~~Adopted rows have no recorded stop~~ — fixed 2026-08-29, commits
   `5980e4c` / `80d85c6`. Recovered from the live order book and now
   self-healing behind reconciliation. **The trap to remember:** those rows
   carry `entry == stop`, so a literal read gives ~$0 of risk — far more
   dangerous than the overstatement being fixed. `equity_stop_distance()` is
   the shared guard; anything reading `long_strike` as a stop must go through
   it.
2. ~~`SECTORS` is a 19-ticker stub~~ — fixed 2026-08-30, commit `2971255`.
   `sector_cache` resolves ticker to sector from yfinance daily (102/102 on
   its first production run) and "Unknown" is no longer treated as a sector by
   any of the four gates that were capping it.

## 6. Automation (§15–§19, §46, §47)

**No Automation Policy subsystem exists.** No persisted per-trade rule object,
no entry-condition evaluator, no policy lifecycle.

Nearest existing analogues: execution modes (manual / copilot / autopilot),
the pending-approval queue, `ExecutionEvent` audit rows, and the rotation
approval path shipped 2026-08-28 — which is structurally the pattern §15
describes (review → approve → execute, never auto-execute).

**Verdict: separate project, weeks not days.** Do not fold it into a mobile
pass.

## 7. Options coverage reality

**One options trade in the entire history. Zero open options positions.**

Every worked example in the spec is an options structure. The options scan,
`options_intelligence`, and the 2-leg close path all exist and are tested, but
the surface is essentially unexercised in production. A mobile experience
built primarily around options cards would be demonstrating a path this desk
has run once.

---

## Recommended sequencing

1. ~~**Fix `position_risk_dollars`**~~ — done 2026-08-29, commit `8afa80c`.
   Next in this line: backfill stops for adopted rows, and stop treating
   "Unknown" as a sector.
2. **Decide the POP presentation.** Show the Black-Scholes POP labelled
   risk-neutral, ideally beside the 7.0% empirical target-hit rate so the gap
   between model and record is visible rather than hidden.
3. **Build the ~15 no-new-data mobile sections**: bottom nav, bottom sheets,
   compact cards, 44px targets, safe areas, responsive tests. Genuinely
   shippable. ~~category tabs~~ — struck 2026-08-30, see §2: the taxonomy
   they were to be built on does not exist.
4. **Then** decide whether to buy a flow feed (§5), define the four missing
   categories (§6), add an invalidation field (§28), and scope Automation
   Policy (§15–19) as its own project.

Sections 1–3 need no new data sources and no new backend subsystems.
