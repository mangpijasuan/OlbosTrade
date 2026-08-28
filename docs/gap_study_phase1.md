# Overnight Gap Study — Phase 1 (empirical validation only)

**Question.** After an overnight gap between prior close and next open, does the following regular session continue in the gap direction, or revert toward the prior close?

**No execution code was written for this phase.** This report is analysis only.

---

## Bottom line

**No tradeable gap effect survives honest error bars.** Neither fade nor continuation.

1. **Pooled across everything, there is nothing.** Mean continuation return −0.017%, date-clustered 95% CI [−0.046%, +0.011%] — spans zero.
2. **No gap-size bucket clears zero** once observations are clustered by date. The naive intervals make three of the four look significant; that precision is an artefact of counting ~100 correlated symbols as ~100 independent facts.
3. **The one apparently-significant slice is a mirage.** Down gaps look like they fade — but 'fade a down gap' is just 'be long from the open', and this sample's unconditional intraday drift is already positive. Against that baseline, **not one** direction × size segment shows a gap effect that excludes zero. See the drift control below; it is the single most important table in this report.
4. **Even the gross numbers mostly lose to a spread.** Only the 2%+ bucket exceeds an optimistic 5 bps round trip, and it does so on an effect that fails the drift control.

**Recommendation: do not proceed to Phase 2 on this evidence.** Extended-hours execution would make the bar *higher*, not lower — wider spreads, thinner books, worse fills — while the measured edge here is indistinguishable from zero in regular hours, which is the friendlier environment. Building `outsideRth` order plumbing to harvest an effect this study cannot detect would be building on nothing.

The closest thing to a live thread is **2%+ gap downs**: +0.197% excess over drift, the largest in the table, with a clustered CI of [−0.016%, +0.427%] that just fails to exclude zero. That is a hypothesis worth a dedicated study (single deep-liquidity instrument, intraday entry timing, exit rules other than 'hold to close'), not a green light.

---

## Data

- **Universe:** 102 symbols — the production equity watchlist (`settings.get_equity_watchlist()`), not a hand-picked sample.
- **Window:** 2015-01-05 → 2026-08-26
- **Observations:** 261,566 symbol-days with a non-zero gap across 2,928 trading dates.
- **Source:** the app's own `DataFetcher.fetch_ohlcv` (broker first, yfinance fallback — the same path the existing backtester uses), split/dividend adjusted.
- **Earnings dates:** 7,825 real announcement dates covering 102/102 symbols.
- **Excluded:** 8 rows with |gap| > 50% (treated as adjustment artefacts, not tradeable events).

**Definitions.** `gap = open/prev_close − 1`; `O→C = close/open − 1`; `continuation = sign(gap) × O→C`.

> **A fade trade and a continuation trade are the same number with opposite signs.** They are not two independent results: the fade mean is exactly −(continuation mean), and the two win rates sum to 100% minus exact-zero days. Both are shown because they were asked for, but only one of them is information.

## Why two confidence intervals

On an index-wide gap morning, all ~100 symbols are reacting to one event. Treating those as 100 independent observations overstates precision badly. Every table therefore carries a **naive** interval (rows independent — usually too narrow to believe) and a **date-clustered** bootstrap interval that resamples whole trading dates. **Read the clustered one.** The `Dates` column is the honest sample size.

**On multiple comparisons:** this report shows roughly 30 segments. At a 95% level you should expect 1–2 to clear zero by chance alone. A segment is worth acting on only if it is large, coherent with its neighbours (a monotone trend across adjacent size buckets, say), and survives costs — not merely because its interval happens to miss zero.

## Overall

| Segment | N | Dates | Mean O→C (raw) | Mean cont. | 95% CI (naive) | 95% CI (date-clustered) | Cont. win % | Fade win % |
|---|---|---|---|---|---|---|---|---|
| All gaps | 261,566 | 2,928 | 0.043% | -0.017% | [-0.025%, -0.010%] | [-0.046%, 0.011%] | 48.8% [48.6–49.0] | 50.7% [50.5–50.9] |

**Verdict:** no edge either way (clustered CI spans 0).

## By gap size

| Gap size | N | Dates | Mean O→C (raw) | Mean cont. | 95% CI (naive) | 95% CI (date-clustered) | Cont. win % | Fade win % |
|---|---|---|---|---|---|---|---|---|
| <0.5% | 135,721 | 2,907 | 0.019% | 0.001% | [-0.007%, 0.009%] | [-0.014%, 0.015%] | 49.0% [48.7–49.2] | 50.6% [50.3–50.8] |
| 0.5-1% | 62,361 | 2,919 | 0.041% | -0.027% | [-0.042%, -0.013%] | [-0.059%, 0.006%] | 48.5% [48.1–48.9] | 51.1% [50.7–51.5] |
| 1-2% | 40,661 | 2,897 | 0.073% | -0.020% | [-0.042%, 0.003%] | [-0.083%, 0.041%] | 49.1% [48.6–49.6] | 50.5% [50.0–51.0] |
| 2%+ | 22,823 | 2,721 | 0.134% | -0.095% | [-0.142%, -0.048%] | [-0.241%, 0.055%] | 48.1% [47.5–48.8] | 51.0% [50.4–51.7] |

- **<0.5%** — no edge either way (clustered CI spans 0)
- **0.5-1%** — no edge either way (clustered CI spans 0)
- **1-2%** — no edge either way (clustered CI spans 0)
- **2%+** — no edge either way (clustered CI spans 0)

## By gap size and direction

Gap-ups and gap-downs need not behave alike; pooling them can hide opposing effects.

| Segment | N | Dates | Mean O→C (raw) | Mean cont. | 95% CI (naive) | 95% CI (date-clustered) | Cont. win % | Fade win % |
|---|---|---|---|---|---|---|---|---|
| <0.5% · gap up | 73,120 | 2,877 | 0.018% | 0.018% | [0.007%, 0.029%] | [-0.014%, 0.049%] | 50.3% [49.9–50.6] | 49.3% [48.9–49.6] |
| <0.5% · gap down | 62,601 | 2,869 | 0.019% | -0.019% | [-0.032%, -0.007%] | [-0.056%, 0.015%] | 47.5% [47.1–47.9] | 52.1% [51.7–52.5] |
| 0.5-1% · gap up | 34,873 | 2,701 | 0.012% | 0.012% | [-0.007%, 0.031%] | [-0.037%, 0.062%] | 50.2% [49.6–50.7] | 49.4% [48.8–49.9] |
| 0.5-1% · gap down | 27,488 | 2,622 | 0.078% | -0.078% | [-0.100%, -0.055%] | [-0.135%, -0.021%] | 46.3% [45.7–46.9] | 53.3% [52.7–53.9] |
| 1-2% · gap up | 21,715 | 2,503 | 0.050% | 0.050% | [0.019%, 0.081%] | [-0.039%, 0.138%] | 50.9% [50.3–51.6] | 48.6% [47.9–49.3] |
| 1-2% · gap down | 18,946 | 2,294 | 0.099% | -0.099% | [-0.132%, -0.066%] | [-0.200%, 0.000%] | 47.0% [46.3–47.7] | 52.6% [51.9–53.3] |
| 2%+ · gap up | 11,899 | 2,200 | 0.038% | 0.038% | [-0.027%, 0.103%] | [-0.160%, 0.231%] | 49.1% [48.2–50.0] | 50.1% [49.2–51.0] |
| 2%+ · gap down | 10,924 | 1,993 | 0.240% | -0.240% | [-0.307%, -0.173%] | [-0.487%, -0.007%] | 47.0% [46.1–48.0] | 52.1% [51.2–53.1] |

### Control: is this just intraday long drift?

Every segment above has a **positive** raw open-to-close mean, because this sample's unconditional intraday drift is positive: **0.043%** across all 261,566 observations. That matters for reading the direction table. 'Fade a down gap' is mechanically 'be long from the open', so a down-gap segment only carries *gap* information if it beats simply being long on an average day.

Below, each segment's mean O→C is differenced against the universe mean **within every bootstrap draw**, so the shared market factor cancels instead of being treated as a known constant. This is the column that decides whether there is a gap effect at all.

| Segment | N | Mean O→C | Excess over universe | 95% CI on excess (date-clustered) | Beats drift? |
|---|---|---|---|---|---|
| <0.5% · gap up | 73,120 | 0.018% | -0.024% | [-0.051%, 0.001%] | no (CI spans 0) |
| <0.5% · gap down | 62,601 | 0.019% | -0.023% | [-0.051%, 0.004%] | no (CI spans 0) |
| 0.5-1% · gap up | 34,873 | 0.012% | -0.030% | [-0.066%, 0.007%] | no (CI spans 0) |
| 0.5-1% · gap down | 27,488 | 0.078% | 0.035% | [-0.008%, 0.081%] | no (CI spans 0) |
| 1-2% · gap up | 21,715 | 0.050% | 0.007% | [-0.069%, 0.079%] | no (CI spans 0) |
| 1-2% · gap down | 18,946 | 0.099% | 0.056% | [-0.027%, 0.140%] | no (CI spans 0) |
| 2%+ · gap up | 11,899 | 0.038% | -0.005% | [-0.191%, 0.181%] | no (CI spans 0) |
| 2%+ · gap down | 10,924 | 0.240% | 0.197% | [-0.016%, 0.427%] | no (CI spans 0) |

## By catalyst

Classification is data-internal and fixed before any return was examined:

- **earnings** — a real announcement date falls in the overnight window that produced the gap (after the prior close, or before this open).
- **macro/index-wide** — on that date, ≥70% of the universe gapped the same way with a median |gap| ≥ 0.3%, and the symbol has no earnings that morning.
- **no identifiable news** — neither, for a symbol that does have earnings coverage.
- **unclassifiable** — symbol has no earnings history available, so a quiet gap cannot be distinguished from an unrecorded earnings gap. Reported separately rather than folded in.

| Catalyst | N | Dates | Mean O→C (raw) | Mean cont. | 95% CI (naive) | 95% CI (date-clustered) | Cont. win % | Fade win % |
|---|---|---|---|---|---|---|---|---|
| earnings | 8,234 | 1,897 | 0.019% | 0.013% | [-0.054%, 0.080%] | [-0.057%, 0.082%] | 49.7% [48.6–50.8] | 50.0% [48.9–51.1] |
| macro/index-wide | 139,690 | 1,612 | 0.053% | -0.012% | [-0.022%, -0.001%] | [-0.060%, 0.034%] | 49.6% [49.3–49.8] | 50.0% [49.7–50.2] |
| no identifiable news | 113,642 | 1,316 | 0.031% | -0.027% | [-0.038%, -0.016%] | [-0.050%, -0.003%] | 47.8% [47.5–48.1] | 51.7% [51.4–52.0] |
| unclassifiable (no earnings coverage) | 0 | — | — | — | — | — | — | — |

- **earnings** — no edge either way (clustered CI spans 0)
- **macro/index-wide** — no edge either way (clustered CI spans 0)
- **no identifiable news** — fade (clustered CI excludes 0)

## Catalyst × gap size

| Segment | N | Dates | Mean O→C (raw) | Mean cont. | 95% CI (naive) | 95% CI (date-clustered) | Cont. win % | Fade win % |
|---|---|---|---|---|---|---|---|---|
| earnings · <0.5% | 2,218 | 1,075 | -0.026% | 0.112% | [0.026%, 0.199%] | [0.029%, 0.200%] | 50.7% [48.6–52.8] | 49.1% [47.0–51.1] |
| earnings · 0.5-1% | 1,366 | 836 | 0.057% | 0.007% | [-0.119%, 0.134%] | [-0.126%, 0.136%] | 48.4% [45.7–51.0] | 51.2% [48.5–53.8] |
| earnings · 1-2% | 1,467 | 852 | -0.003% | -0.099% | [-0.241%, 0.044%] | [-0.237%, 0.045%] | 49.0% [46.5–51.6] | 50.6% [48.0–53.1] |
| earnings · 2%+ | 3,183 | 1,303 | 0.045% | -0.002% | [-0.139%, 0.135%] | [-0.151%, 0.141%] | 49.9% [48.2–51.7] | 49.9% [48.2–51.7] |
| macro/index-wide · <0.5% | 55,283 | 1,590 | 0.017% | 0.024% | [0.011%, 0.036%] | [-0.003%, 0.051%] | 50.0% [49.6–50.5] | 49.6% [49.1–50.0] |
| macro/index-wide · 0.5-1% | 40,215 | 1,603 | 0.044% | -0.007% | [-0.024%, 0.010%] | [-0.053%, 0.036%] | 49.4% [48.9–49.9] | 50.1% [49.6–50.6] |
| macro/index-wide · 1-2% | 29,525 | 1,606 | 0.077% | -0.020% | [-0.045%, 0.005%] | [-0.100%, 0.059%] | 49.7% [49.1–50.3] | 49.9% [49.4–50.5] |
| macro/index-wide · 2%+ | 14,667 | 1,477 | 0.169% | -0.140% | [-0.196%, -0.084%] | [-0.364%, 0.064%] | 47.9% [47.1–48.7] | 51.3% [50.4–52.1] |
| no identifiable news · <0.5% | 78,220 | 1,316 | 0.021% | -0.018% | [-0.029%, -0.008%] | [-0.034%, -0.004%] | 48.2% [47.8–48.5] | 51.3% [50.9–51.6] |
| no identifiable news · 0.5-1% | 20,780 | 1,316 | 0.034% | -0.069% | [-0.096%, -0.041%] | [-0.109%, -0.030%] | 46.6% [45.9–47.3] | 53.0% [52.3–53.7] |
| no identifiable news · 1-2% | 9,669 | 1,282 | 0.071% | -0.007% | [-0.060%, 0.047%] | [-0.087%, 0.075%] | 47.3% [46.3–48.3] | 52.2% [51.2–53.2] |
| no identifiable news · 2%+ | 4,973 | 1,088 | 0.091% | -0.022% | [-0.127%, 0.084%] | [-0.221%, 0.175%] | 47.5% [46.1–48.9] | 51.2% [49.8–52.5] |

## Does any of this clear a spread?

Gross of costs throughout. For scale, a round-trip hurdle in basis points of notional:

| Segment | Mean edge (bps) | vs RTH liquid, mid-ish (5 bps) | vs RTH realistic (10 bps) |
|---|---|---|---|
| All gaps | -1.75 | short by 3.3 bps | short by 8.3 bps |
| <0.5% | +0.08 | short by 4.9 bps | short by 9.9 bps |
| 0.5-1% | -2.75 | short by 2.3 bps | short by 7.3 bps |
| 1-2% | -1.95 | short by 3.0 bps | short by 8.0 bps |
| 2%+ | -9.50 | clears by 4.5 bps | short by 0.5 bps |

These hurdles are a yardstick, not a fill model. They assume regular-hours liquidity at roughly mid. The opening auction is the widest, most adversarial moment of the session, so even the optimistic column is generous for a trade that enters at the open.
