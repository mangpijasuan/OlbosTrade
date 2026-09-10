"""
Calibration for confidence_skill_test.py — how much should its verdict be believed?

confidence_skill_test.py prints an AUC, a date-clustered 95% CI, and a verdict
("BEATS / WORSE THAN / INDISTINGUISHABLE FROM a coin flip"). Whether that
verdict means anything depends on a question the test cannot answer about
itself: at the sample size actually available (~14 trading days, ~52 tickers
sharing each day), does that interval cover the truth 95% of the time?

This script answers it by simulation. It builds data with NO skill by
construction — confidence and hit-rate both vary day to day, independently of
each other, which is what real market days look like (whole days run hot or
cold) — and counts how often each interval wrongly excludes 0.5. It imports the
real `auc()` from the test rather than reimplementing it, so it is calibrating
the estimator that actually ships.

This produces NO skill result and touches no database. It says how to read the
number that confidence_skill_test.py produces when run where the data lives.

Recorded result (2026-09-10) — the defaults below reproduce it, ~7 minutes:

    python scripts/confidence_skill_calibration.py     # 500 reps x 2000 draws, seed 4242

    clustered CI coverage  91.2%  ->  8.8% false positives  (nominal 5%)
    naive     CI coverage  82.6%  -> 17.4% false positives
    null AUC spread        0.503 +/- 0.059, range [0.319, 0.673]

`--draws` defaults to 2000 to match confidence_skill_test.py's own DRAWS. That
matters: calibrating with fewer draws measures a noisier interval than the one
that ships and overstates its false-positive rate. Coverage is a Monte-Carlo
estimate — at 500 reps its standard error is ~1.3 points, so read these to the
nearest point, not the decimal.

Two conclusions, both load-bearing when reading a real run:

1. The date-clustering earns its place — it roughly halves the false-positive
   rate (17.4% -> 8.8%). A naive row-bootstrap would announce skill on about
   one run in six of data that has none.
2. Even clustered, the interval is anti-conservative at this sample size
   (~1.8x the nominal false-positive rate), and the point estimate is barely
   informative: a signal with zero skill produced AUCs from 0.32 to 0.67. An
   observed AUC near 0.55-0.60 whose CI just clears 0.5 is NOT evidence of
   edge. Re-run once the sample spans months rather than days.

Usage:  python scripts/confidence_skill_calibration.py [--reps N] [--draws N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from confidence_skill_test import auc  # noqa: E402

# Shape of the real sample this is calibrating for: the assessment measured
# ~1,568 distinct (ticker, action, day) rows across 14 market days, ~52 tickers
# sharing each day, with a ~7% target_hit base rate among decided outcomes.
N_DAYS = 14
PER_DAY = 52
BASE_RATE = 0.07

# Day-to-day dispersion. The exact values matter less than their presence:
# what drives the finding is that both quantities move together within a day
# and independently across days.
CONF_DAY_SD = 0.06     # how much a whole day's confidence level drifts
CONF_ROW_SD = 0.05     # per-signal spread within a day
RATE_DAY_SD = 0.05     # how much a whole day's hit rate drifts


def make_null(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build one dataset whose true AUC is 0.500.

    Confidence and outcome are each clustered by day but drawn independently of
    one another, so no information about the outcome is present in confidence.
    Any AUC away from 0.5 in the result is sampling noise — which is exactly
    what the interval is supposed to account for.
    """
    dates: list[int] = []
    conf: list[float] = []
    lab: list[int] = []
    for day in range(N_DAYS):
        conf_shift = rng.normal(0, CONF_DAY_SD)
        day_rate = float(np.clip(BASE_RATE + rng.normal(0, RATE_DAY_SD), 0.01, 0.5))
        for _ in range(PER_DAY):
            dates.append(day)
            conf.append(float(np.clip(0.72 + conf_shift + rng.normal(0, CONF_ROW_SD), 0.0, 1.0)))
            lab.append(1 if rng.random() < day_rate else 0)
    return np.array(conf), np.array(lab), np.array(dates)


def clustered_ci(conf, lab, dates, rng, draws) -> tuple[float, float]:
    """Resample whole days with replacement — mirrors the test's own block."""
    uniq = np.unique(dates)
    idx_by_date = {d: np.flatnonzero(dates == d) for d in uniq}
    boots = []
    for _ in range(draws):
        picked = rng.choice(uniq, size=len(uniq), replace=True)
        sel = np.concatenate([idx_by_date[d] for d in picked])
        a = auc(conf[sel], lab[sel])
        if not np.isnan(a):
            boots.append(a)
    return tuple(np.percentile(boots, [2.5, 97.5])) if boots else (np.nan, np.nan)


def naive_ci(conf, lab, rng, draws) -> tuple[float, float]:
    """Resample individual rows — the interval that ignores day clustering."""
    n = len(lab)
    boots = []
    for _ in range(draws):
        sel = rng.integers(0, n, n)
        a = auc(conf[sel], lab[sel])
        if not np.isnan(a):
            boots.append(a)
    return tuple(np.percentile(boots, [2.5, 97.5])) if boots else (np.nan, np.nan)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=500, help="null datasets to simulate")
    parser.add_argument("--draws", type=int, default=2000,
                        help="bootstrap draws per dataset; 2000 matches the shipping test")
    parser.add_argument("--seed", type=int, default=4242)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    clustered_hits = naive_hits = 0
    clustered_widths: list[float] = []
    naive_widths: list[float] = []
    point_aucs: list[float] = []

    for _ in range(args.reps):
        conf, lab, dates = make_null(rng)
        point_aucs.append(auc(conf, lab))

        c_lo, c_hi = clustered_ci(conf, lab, dates, rng, args.draws)
        n_lo, n_hi = naive_ci(conf, lab, rng, args.draws)

        if not np.isnan(c_lo):
            clustered_hits += int(c_lo <= 0.5 <= c_hi)
            clustered_widths.append(c_hi - c_lo)
        if not np.isnan(n_lo):
            naive_hits += int(n_lo <= 0.5 <= n_hi)
            naive_widths.append(n_hi - n_lo)

    pts = np.array(point_aucs)
    print("=" * 68)
    print("CONFIDENCE SKILL TEST — INTERVAL CALIBRATION (simulated null)")
    print("=" * 68)
    print(f"design           : {N_DAYS} days x {PER_DAY}/day, base rate {BASE_RATE:.0%}, "
          f"true AUC 0.500 by construction")
    print(f"replications     : {args.reps}   bootstrap draws each: {args.draws}   seed: {args.seed}")
    print()
    print(f"null AUC spread  : {pts.mean():.3f} +/- {pts.std():.3f}   "
          f"range [{pts.min():.3f}, {pts.max():.3f}]")
    print("                   ^ a signal with NO skill lands anywhere in this range")
    print()
    print(f"clustered CI     : {100*clustered_hits/args.reps:5.1f}% coverage   "
          f"{100*(1-clustered_hits/args.reps):4.1f}% false positives   "
          f"mean width {np.mean(clustered_widths):.3f}")
    print(f"naive CI         : {100*naive_hits/args.reps:5.1f}% coverage   "
          f"{100*(1-naive_hits/args.reps):4.1f}% false positives   "
          f"mean width {np.mean(naive_widths):.3f}")
    print(f"nominal          :  95.0% coverage    5.0% false positives")
    print()
    print("Reading a real run: clustering roughly halves the false-positive rate,")
    print("but at this sample size even the clustered interval is anti-conservative.")
    print("An observed AUC near 0.55-0.60 whose CI just clears 0.5 is not evidence.")


if __name__ == "__main__":
    main()
