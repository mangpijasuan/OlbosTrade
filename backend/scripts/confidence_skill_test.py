"""
Does the deterministic signal engine's confidence beat a coin flip?

Scope, stated precisely: this measures `signal_outcomes.confidence`, produced by
`score_equity_signal()` and stored at signal-generation time. It is NOT the
Alpha Edge score — `compute_equity_alpha_edge()` is only ever called from the
on-demand /api/alpha-edge/{ticker} route and is never persisted, so no
historical Alpha Edge value exists to test. Confidence is the score that
actually gates routing, which makes it the more decision-relevant of the two.

Metric is AUC (equivalently Mann-Whitney U): the probability that a randomly
chosen target_hit signal carried higher confidence than a randomly chosen
stop_hit one. 0.5 is a coin flip. AUC is used rather than accuracy because the
base rate is ~7% — a model predicting "stop" every time would score 93%
accuracy and be worthless.

Inference is a date-clustered bootstrap. ~52 tickers share each trading day, so
rows are nowhere near independent; the gap study on this same universe showed
naive intervals collapsing once dates were clustered.

Read-only. No writes, no orders.

Usage:  python scripts/confidence_skill_test.py
"""

from __future__ import annotations

import asyncio
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402

RNG = np.random.default_rng(20260828)
DRAWS = 2000


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Rank-based AUC. Ties get average ranks, which is the correct
    handling here — confidence is coarsely quantised and ties are common."""
    pos, neg = int(labels.sum()), int((1 - labels).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    r = stats.rankdata(scores)
    return (r[labels == 1].sum() - pos * (pos + 1) / 2) / (pos * neg)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p, d = k / n, 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (c - h, c + h)


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT confidence, status, generated_at::date AS d, ticker
            FROM signal_outcomes
            WHERE status IN ('target_hit', 'stop_hit') AND confidence IS NOT NULL
        """))).fetchall()

    if not rows:
        print("no decided outcomes"); return

    conf = np.array([float(r[0]) for r in rows])
    lab = np.array([1 if r[1] == "target_hit" else 0 for r in rows])
    dates = np.array([str(r[2]) for r in rows])
    tickers = np.array([r[3] for r in rows])

    n, npos = len(lab), int(lab.sum())
    print("=" * 66)
    print("DETERMINISTIC CONFIDENCE — SKILL TEST")
    print("=" * 66)
    print(f"decided outcomes : {n:,}  ({npos:,} target_hit / {n-npos:,} stop_hit)")
    print(f"base rate        : {100*npos/n:.2f}% target")
    print(f"distinct dates   : {len(set(dates))}   distinct tickers: {len(set(tickers))}")
    print(f"confidence range : {conf.min():.4f} .. {conf.max():.4f}  "
          f"(sd {conf.std():.4f}, {len(np.unique(conf))} distinct values)")

    point = auc(conf, lab)
    print(f"\nAUC              : {point:.4f}    (0.500 = coin flip)")

    # ── date-clustered bootstrap ──
    uniq = np.unique(dates)
    idx_by_date = {d: np.flatnonzero(dates == d) for d in uniq}
    boots = []
    for _ in range(DRAWS):
        picked = RNG.choice(uniq, size=len(uniq), replace=True)
        sel = np.concatenate([idx_by_date[d] for d in picked])
        a = auc(conf[sel], lab[sel])
        if not np.isnan(a):
            boots.append(a)
    boots = np.array(boots)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"95% CI (clustered): [{lo:.4f}, {hi:.4f}]   over {len(uniq)} dates")

    # Naive (row-independent) interval, for contrast only.
    nb = []
    for _ in range(DRAWS):
        sel = RNG.integers(0, n, n)
        a = auc(conf[sel], lab[sel])
        if not np.isnan(a):
            nb.append(a)
    nlo, nhi = np.percentile(np.array(nb), [2.5, 97.5])
    print(f"95% CI (naive)    : [{nlo:.4f}, {nhi:.4f}]   <- too narrow to believe")

    verdict = ("BEATS a coin flip" if lo > 0.5 else
               "WORSE than a coin flip" if hi < 0.5 else
               "INDISTINGUISHABLE from a coin flip")
    print(f"\nVERDICT: {verdict} (clustered CI vs 0.5)")

    # ── monotonicity: does a higher bucket actually hit more often? ──
    print("\n" + "-" * 66)
    print("HIT RATE BY CONFIDENCE BUCKET (target / decided)")
    print("-" * 66)
    edges = [0.0, 0.65, 0.70, 0.75, 0.80, 1.01]
    names = ["<0.65", "0.65-0.70", "0.70-0.75", "0.75-0.80", "0.80+"]
    for name, a, b in zip(names, edges[:-1], edges[1:]):
        m = (conf >= a) & (conf < b)
        k, tot = int(lab[m].sum()), int(m.sum())
        if tot == 0:
            print(f"  {name:10} {'—':>8}   n=0")
            continue
        wl, wh = wilson(k, tot)
        print(f"  {name:10} {100*k/tot:7.2f}%   n={tot:6,}   95% CI "
              f"[{100*wl:.2f}%, {100*wh:.2f}%]")

    print("\n" + "-" * 66)
    print("CAVEAT — this is a CENSORED sample")
    print("-" * 66)
    print("Only decided outcomes appear above. 86.9% of all signals are still")
    print("pending, and resolution is biased toward fast movers (stops resolve")
    print("sooner than targets). 'expired' has never fired — max bars elapsed is")
    print("~9 against a 20-bar horizon. Whatever this AUC says, it describes the")
    print("subset that resolved quickly, not the population of signals.")


if __name__ == "__main__":
    asyncio.run(main())
