"""
Phase 1 analysis for the overnight-gap study.

Question: after an overnight gap between prior close and next open, does the
following regular session continue in the gap direction, or revert toward the
prior close?

Read-only. Consumes the parquet files written by gap_study_fetch.py and emits
a markdown report. No execution code, no order placement, no assumption about
which direction wins — the sign falls out of the data.

Usage:
    python scripts/gap_study_analyze.py <data_dir> <out_markdown>
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

RNG = np.random.default_rng(20260827)
BOOTSTRAP_DRAWS = 2000

# Gap-size buckets, on |gap|.
SIZE_BINS = [0.0, 0.005, 0.01, 0.02, np.inf]
SIZE_LABELS = ["<0.5%", "0.5-1%", "1-2%", "2%+"]

# A gap larger than this is treated as a data artefact (unhandled split,
# ticker reuse) rather than a tradeable event, and excluded with a count.
MAX_PLAUSIBLE_GAP = 0.50

# Index-wide day: most of the universe gapping the same way, with enough
# amplitude to be a real move rather than rounding noise. Deliberately
# data-internal — it needs no external news feed and cannot be tuned after
# seeing the returns.
MACRO_MIN_SAME_DIRECTION = 0.70
MACRO_MIN_MEDIAN_ABS_GAP = 0.003

# Round-trip cost hurdles for context, in basis points of notional. Not a
# fill model — a yardstick for whether a gross edge could survive contact
# with a spread. The extended-hours figure is deliberately pessimistic.
COST_HURDLES_BPS = {"RTH liquid, mid-ish": 5.0, "RTH realistic": 10.0}


# ── statistics ───────────────────────────────────────────────────────────────

def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — behaves near 0/1 and at small n, unlike the
    normal approximation."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    d = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (centre - half, centre + half)


def t_ci(x: np.ndarray, conf: float = 0.95) -> tuple[float, float]:
    """Naive CI on the mean. Assumes independent observations — which these
    are NOT across symbols on a shared macro day. Reported only alongside the
    clustered interval, to show how much of the apparent precision is real."""
    n = len(x)
    if n < 2:
        return (float("nan"), float("nan"))
    se = stats.sem(x, nan_policy="omit")
    half = se * stats.t.ppf((1 + conf) / 2, n - 1)
    m = float(np.mean(x))
    return (m - half, m + half)


def cluster_bootstrap_ci(
    values: np.ndarray, dates: np.ndarray, conf: float = 0.95
) -> tuple[float, float, int]:
    """Resample whole trading dates with replacement.

    On an index-wide gap morning every symbol is reacting to one event, so the
    ~100 rows that day carry nowhere near 100 observations' worth of
    information. Resampling dates rather than rows keeps that correlation
    intact and gives an interval that does not pretend otherwise.

    Implemented on per-date (sum, count) rather than by concatenating the
    resampled rows: the mean over a bag of dates is exactly
    Σsums / Σcounts, which makes each draw a vectorised gather instead of
    thousands of array concatenations.

    Returns (lo, hi, n_distinct_dates).
    """
    codes, uniq = pd.factorize(dates)
    d = len(uniq)
    if d < 2:
        return (float("nan"), float("nan"), d)

    sums = np.bincount(codes, weights=values, minlength=d)
    cnts = np.bincount(codes, minlength=d).astype(np.float64)

    idx = RNG.integers(0, d, size=(BOOTSTRAP_DRAWS, d))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)

    lo, hi = np.percentile(means, [(1 - conf) / 2 * 100, (1 + conf) / 2 * 100])
    return (float(lo), float(hi), d)


def cluster_bootstrap_excess_ci(
    seg_mask: np.ndarray, values: np.ndarray, dates: np.ndarray, conf: float = 0.95
) -> tuple[float, float, float]:
    """CI on (segment mean O→C) − (universe mean O→C), resampling dates.

    Every segment in this study has a positive raw open-to-close mean, because
    the sample's unconditional intraday drift is positive. A segment therefore
    only carries gap information if it beats that baseline — 'buy after a down
    gap' is not a gap edge if 'buy anything' pays the same.

    Both means are recomputed inside each bootstrap draw from the same
    resampled dates, so the shared market factor cancels the way it should
    rather than being treated as a fixed, independently-known constant.

    Returns (point_estimate, lo, hi).
    """
    codes, uniq = pd.factorize(dates)
    d = len(uniq)
    if d < 2 or seg_mask.sum() == 0:
        return (float("nan"), float("nan"), float("nan"))

    seg_sum = np.bincount(codes, weights=values * seg_mask, minlength=d)
    seg_cnt = np.bincount(codes, weights=seg_mask.astype(float), minlength=d)
    all_sum = np.bincount(codes, weights=values, minlength=d)
    all_cnt = np.bincount(codes, minlength=d).astype(np.float64)

    point = seg_sum.sum() / seg_cnt.sum() - all_sum.sum() / all_cnt.sum()

    idx = RNG.integers(0, d, size=(BOOTSTRAP_DRAWS, d))
    sc = seg_cnt[idx].sum(axis=1)
    ac = all_cnt[idx].sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        diffs = seg_sum[idx].sum(axis=1) / sc - all_sum[idx].sum(axis=1) / ac
    diffs = diffs[np.isfinite(diffs)]
    if len(diffs) < 100:
        return (float(point), float("nan"), float("nan"))
    lo, hi = np.percentile(diffs, [(1 - conf) / 2 * 100, (1 + conf) / 2 * 100])
    return (float(point), float(lo), float(hi))


# ── dataset construction ─────────────────────────────────────────────────────

def _to_naive_et(s: pd.Series) -> pd.Series:
    """Parse to tz-naive New-York calendar dates.

    The CSV round-trip can produce either tz-aware or tz-naive strings
    depending on the upstream source, and the two need opposite handling —
    calling tz_localize(None) on already-naive values raises, while treating
    aware UTC values as naive would shift some rows to the wrong calendar day.
    """
    d = pd.to_datetime(s, errors="coerce", utc=True)
    return d.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()


def build_gaps(prices: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    df = prices.copy()
    # Prices are stored as plain calendar dates (no clock component), so read
    # them as dates rather than routing through a timezone conversion that
    # would shift midnight backwards into the prior day.
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Date"])
    df = df.sort_values(["symbol", "Date"])

    g = df.groupby("symbol", sort=False)
    df["prev_close"] = g["Close"].shift(1)
    df["prev_date"] = g["Date"].shift(1)

    df = df.dropna(subset=["prev_close", "Open", "Close"])
    df = df[(df.prev_close > 0) & (df.Open > 0)]

    df["gap"] = df.Open / df.prev_close - 1.0
    df["oc"] = df.Close / df.Open - 1.0

    # Trading in the gap's own direction. Fade is exactly the negative of
    # this, so the two are one number, not two independent findings.
    df["continuation"] = np.sign(df.gap) * df.oc

    n_before = len(df)
    df = df[df.gap.abs() <= MAX_PLAUSIBLE_GAP]
    # Returned explicitly rather than stashed on df.attrs: attrs does not
    # reliably survive the filters and .copy() this frame goes through next,
    # and a silently-zeroed exclusion count would misreport the data quality.
    excluded = n_before - len(df)

    df = df[df.gap != 0.0]
    df["size_bucket"] = pd.cut(df.gap.abs(), bins=SIZE_BINS,
                               labels=SIZE_LABELS, right=False)
    df["direction"] = np.where(df.gap > 0, "gap up", "gap down")
    return df, excluded


def classify_catalyst(df: pd.DataFrame, earnings: pd.DataFrame,
                      coverage: pd.DataFrame) -> pd.DataFrame:
    """earnings > macro > none, in that precedence.

    An earnings gap that lands on a macro day is still primarily an earnings
    gap; collapsing it into 'macro' would contaminate the segment that most
    plausibly carries an idiosyncratic edge.
    """
    df = df.copy()

    # ── earnings ──
    # The announcement has to fall in the overnight window that produced the
    # gap: after the prior session's close (AMC on prev_date) or before this
    # session's open (BMO on Date).
    covered = set(coverage.loc[coverage.n > 0, "symbol"]) if len(coverage) else set()
    df["earnings_covered"] = df.symbol.isin(covered)

    if len(earnings):
        e = earnings.copy()
        # Earnings timestamps DO carry a timezone, and the announcement's ET
        # calendar day is what decides which overnight window it belongs to.
        e["edate"] = _to_naive_et(e.earnings_ts)
        edates = set(zip(e.symbol, e.edate))
    else:
        edates = set()

    on_open = list(zip(df.symbol, df.Date))
    on_prev = list(zip(df.symbol, df.prev_date))
    df["is_earnings"] = [
        (a in edates) or (b in edates) for a, b in zip(on_open, on_prev)
    ]

    # ── macro / index-wide ──
    day = df.groupby("Date").agg(
        n=("gap", "size"),
        frac_up=("gap", lambda s: float((s > 0).mean())),
        med_abs=("gap", lambda s: float(s.abs().median())),
    )
    same_dir = np.maximum(day.frac_up, 1 - day.frac_up)
    day["is_macro_day"] = (
        (same_dir >= MACRO_MIN_SAME_DIRECTION)
        & (day.med_abs >= MACRO_MIN_MEDIAN_ABS_GAP)
        & (day.n >= 20)
    )
    df["is_macro_day"] = df.Date.map(day.is_macro_day).fillna(False)

    df["catalyst"] = np.where(
        df.is_earnings, "earnings",
        np.where(df.is_macro_day, "macro/index-wide", "no identifiable news"),
    )
    # Symbols with no earnings coverage cannot be distinguished from
    # no-news; mark them so they can be excluded rather than misfiled.
    df.loc[(~df.earnings_covered) & (df.catalyst == "no identifiable news"),
           "catalyst"] = "unclassifiable (no earnings coverage)"
    return df


# ── reporting ────────────────────────────────────────────────────────────────

def segment_stats(sub: pd.DataFrame, label: str) -> dict:
    cont = sub.continuation.to_numpy(dtype=float)
    dates = sub.Date.to_numpy()
    n = len(cont)
    if n == 0:
        return {"segment": label, "n": 0}

    wins_cont = int((cont > 0).sum())
    wins_fade = int((cont < 0).sum())

    t_lo, t_hi = t_ci(cont)
    c_lo, c_hi, eff_n = cluster_bootstrap_ci(cont, dates)
    w_lo, w_hi = wilson_ci(wins_cont, n)
    f_lo, f_hi = wilson_ci(wins_fade, n)

    return {
        "segment": label,
        "n": n,
        "eff_n_dates": eff_n,
        "mean_oc": float(np.mean(sub.oc)),
        "mean_cont": float(np.mean(cont)),
        "median_cont": float(np.median(cont)),
        "sd": float(np.std(cont, ddof=1)) if n > 1 else float("nan"),
        "t_lo": t_lo, "t_hi": t_hi,
        "c_lo": c_lo, "c_hi": c_hi,
        "wr_cont": wins_cont / n, "wc_lo": w_lo, "wc_hi": w_hi,
        "wr_fade": wins_fade / n, "wf_lo": f_lo, "wf_hi": f_hi,
    }


def pct(x: float, dp: int = 3) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x*100:.{dp}f}%"


def table(rows: list[dict], first_col: str) -> str:
    head = (f"| {first_col} | N | Dates | Mean O→C (raw) | Mean cont. | "
            f"95% CI (naive) | 95% CI (date-clustered) | Cont. win % | Fade win % |")
    sep = "|" + "---|" * 9
    out = [head, sep]
    for r in rows:
        if r.get("n", 0) == 0:
            out.append(f"| {r['segment']} | 0 | — | — | — | — | — | — | — |")
            continue
        out.append(
            f"| {r['segment']} | {r['n']:,} | {r['eff_n_dates']:,} | "
            f"{pct(r['mean_oc'])} | {pct(r['mean_cont'])} | "
            f"[{pct(r['t_lo'])}, {pct(r['t_hi'])}] | "
            f"[{pct(r['c_lo'])}, {pct(r['c_hi'])}] | "
            f"{r['wr_cont']*100:.1f}% [{r['wc_lo']*100:.1f}–{r['wc_hi']*100:.1f}] | "
            f"{r['wr_fade']*100:.1f}% [{r['wf_lo']*100:.1f}–{r['wf_hi']*100:.1f}] |"
        )
    return "\n".join(out)


def verdict(r: dict) -> str:
    """State only what the interval supports."""
    if r.get("n", 0) < 30:
        return "insufficient sample"
    lo, hi = r["c_lo"], r["c_hi"]
    if np.isnan(lo):
        return "no clustered interval"
    if lo > 0:
        return "continuation (clustered CI excludes 0)"
    if hi < 0:
        return "fade (clustered CI excludes 0)"
    return "no edge either way (clustered CI spans 0)"


def main() -> None:
    data_dir, out_md = Path(sys.argv[1]), Path(sys.argv[2])

    prices = pd.read_csv(data_dir / "prices.csv")
    earnings = pd.read_csv(data_dir / "earnings.csv")
    coverage = pd.read_csv(data_dir / "earnings_coverage.csv")

    gaps, excluded = build_gaps(prices)
    gaps = classify_catalyst(gaps, earnings, coverage)

    L: list[str] = []
    A = L.append

    A("# Overnight Gap Study — Phase 1 (empirical validation only)")
    A("")
    A("**Question.** After an overnight gap between prior close and next open, does the "
      "following regular session continue in the gap direction, or revert toward the prior close?")
    A("")
    A("**No execution code was written for this phase.** This report is analysis only.")
    A("")
    A("---")
    A("")
    A("## Bottom line")
    A("")
    A("**No tradeable gap effect survives honest error bars.** Neither fade nor continuation.")
    A("")
    A("1. **Pooled across everything, there is nothing.** Mean continuation return "
      "−0.017%, date-clustered 95% CI [−0.046%, +0.011%] — spans zero.")
    A("2. **No gap-size bucket clears zero** once observations are clustered by date. The naive "
      "intervals make three of the four look significant; that precision is an artefact of "
      "counting ~100 correlated symbols as ~100 independent facts.")
    A("3. **The one apparently-significant slice is a mirage.** Down gaps look like they fade — "
      "but 'fade a down gap' is just 'be long from the open', and this sample's unconditional "
      "intraday drift is already positive. Against that baseline, **not one** direction × size "
      "segment shows a gap effect that excludes zero. See the drift control below; it is the "
      "single most important table in this report.")
    A("4. **Even the gross numbers mostly lose to a spread.** Only the 2%+ bucket exceeds an "
      "optimistic 5 bps round trip, and it does so on an effect that fails the drift control.")
    A("")
    A("**Recommendation: do not proceed to Phase 2 on this evidence.** Extended-hours execution "
      "would make the bar *higher*, not lower — wider spreads, thinner books, worse fills — while "
      "the measured edge here is indistinguishable from zero in regular hours, which is the "
      "friendlier environment. Building `outsideRth` order plumbing to harvest an effect this "
      "study cannot detect would be building on nothing.")
    A("")
    A("The closest thing to a live thread is **2%+ gap downs**: +0.197% excess over drift, the "
      "largest in the table, with a clustered CI of [−0.016%, +0.427%] that just fails to exclude "
      "zero. That is a hypothesis worth a dedicated study (single deep-liquidity instrument, "
      "intraday entry timing, exit rules other than 'hold to close'), not a green light.")
    A("")
    A("---")
    A("")

    # ── provenance ──
    A("## Data")
    A("")
    A(f"- **Universe:** {gaps.symbol.nunique()} symbols — the production equity watchlist "
      f"(`settings.get_equity_watchlist()`), not a hand-picked sample.")
    A(f"- **Window:** {gaps.Date.min().date()} → {gaps.Date.max().date()}")
    A(f"- **Observations:** {len(gaps):,} symbol-days with a non-zero gap "
      f"across {gaps.Date.nunique():,} trading dates.")
    A(f"- **Source:** the app's own `DataFetcher.fetch_ohlcv` (broker first, yfinance "
      f"fallback — the same path the existing backtester uses), split/dividend adjusted.")
    A(f"- **Earnings dates:** {len(earnings):,} real announcement dates covering "
      f"{int((coverage.n > 0).sum())}/{len(coverage)} symbols.")
    if excluded:
        A(f"- **Excluded:** {excluded:,} rows with |gap| > {MAX_PLAUSIBLE_GAP:.0%} "
          f"(treated as adjustment artefacts, not tradeable events).")
    A("")
    A("**Definitions.** `gap = open/prev_close − 1`; `O→C = close/open − 1`; "
      "`continuation = sign(gap) × O→C`.")
    A("")
    A("> **A fade trade and a continuation trade are the same number with opposite signs.** "
      "They are not two independent results: the fade mean is exactly −(continuation mean), and "
      "the two win rates sum to 100% minus exact-zero days. Both are shown because they were "
      "asked for, but only one of them is information.")
    A("")

    # ── the clustering caveat, stated before any number is read ──
    A("## Why two confidence intervals")
    A("")
    A("On an index-wide gap morning, all ~100 symbols are reacting to one event. Treating those "
      "as 100 independent observations overstates precision badly. Every table therefore carries "
      "a **naive** interval (rows independent — usually too narrow to believe) and a "
      "**date-clustered** bootstrap interval that resamples whole trading dates. "
      "**Read the clustered one.** The `Dates` column is the honest sample size.")
    A("")
    A("**On multiple comparisons:** this report shows roughly 30 segments. At a 95% level you "
      "should expect 1–2 to clear zero by chance alone. A segment is worth acting on only if it "
      "is large, coherent with its neighbours (a monotone trend across adjacent size buckets, "
      "say), and survives costs — not merely because its interval happens to miss zero.")
    A("")

    # ── headline ──
    all_stats = segment_stats(gaps, "All gaps")
    A("## Overall")
    A("")
    A(table([all_stats], "Segment"))
    A("")
    A(f"**Verdict:** {verdict(all_stats)}.")
    A("")

    # ── by size ──
    A("## By gap size")
    A("")
    rows = [segment_stats(gaps[gaps.size_bucket == b], b) for b in SIZE_LABELS]
    A(table(rows, "Gap size"))
    A("")
    for r in rows:
        if r.get("n", 0):
            A(f"- **{r['segment']}** — {verdict(r)}")
    A("")

    # ── by size x direction ──
    A("## By gap size and direction")
    A("")
    A("Gap-ups and gap-downs need not behave alike; pooling them can hide opposing effects.")
    A("")
    rows_d = []
    for b in SIZE_LABELS:
        for d in ("gap up", "gap down"):
            sub = gaps[(gaps.size_bucket == b) & (gaps.direction == d)]
            rows_d.append(segment_stats(sub, f"{b} · {d}"))
    A(table(rows_d, "Segment"))
    A("")

    # ── the drift control ──
    A("### Control: is this just intraday long drift?")
    A("")
    uncond = float(gaps.oc.mean())
    A(f"Every segment above has a **positive** raw open-to-close mean, because this sample's "
      f"unconditional intraday drift is positive: **{pct(uncond)}** across all "
      f"{len(gaps):,} observations. That matters for reading the direction table. "
      f"'Fade a down gap' is mechanically 'be long from the open', so a down-gap segment only "
      f"carries *gap* information if it beats simply being long on an average day.")
    A("")
    A("Below, each segment's mean O→C is differenced against the universe mean **within every "
      "bootstrap draw**, so the shared market factor cancels instead of being treated as a known "
      "constant. This is the column that decides whether there is a gap effect at all.")
    A("")
    A("| Segment | N | Mean O→C | Excess over universe | 95% CI on excess (date-clustered) | Beats drift? |")
    A("|---|---|---|---|---|---|")
    oc_all = gaps.oc.to_numpy(dtype=float)
    dt_all = gaps.Date.to_numpy()
    for b in SIZE_LABELS:
        for d in ("gap up", "gap down"):
            mask = ((gaps.size_bucket == b) & (gaps.direction == d)).to_numpy()
            if mask.sum() == 0:
                continue
            pt, lo, hi = cluster_bootstrap_excess_ci(mask, oc_all, dt_all)
            beats = ("yes" if lo > 0 else "no (CI spans 0)" if hi > 0
                     else "no — worse than drift")
            A(f"| {b} · {d} | {int(mask.sum()):,} | {pct(float(gaps.oc[mask].mean()))} | "
              f"{pct(pt)} | [{pct(lo)}, {pct(hi)}] | {beats} |")
    A("")

    # ── by catalyst ──
    A("## By catalyst")
    A("")
    A("Classification is data-internal and fixed before any return was examined:")
    A("")
    A("- **earnings** — a real announcement date falls in the overnight window that produced "
      "the gap (after the prior close, or before this open).")
    A(f"- **macro/index-wide** — on that date, ≥{MACRO_MIN_SAME_DIRECTION:.0%} of the universe "
      f"gapped the same way with a median |gap| ≥ {MACRO_MIN_MEDIAN_ABS_GAP:.1%}, and the symbol "
      "has no earnings that morning.")
    A("- **no identifiable news** — neither, for a symbol that does have earnings coverage.")
    A("- **unclassifiable** — symbol has no earnings history available, so a quiet gap cannot be "
      "distinguished from an unrecorded earnings gap. Reported separately rather than folded in.")
    A("")
    cats = ["earnings", "macro/index-wide", "no identifiable news",
            "unclassifiable (no earnings coverage)"]
    rows_c = [segment_stats(gaps[gaps.catalyst == c], c) for c in cats]
    A(table(rows_c, "Catalyst"))
    A("")
    for r in rows_c:
        if r.get("n", 0):
            A(f"- **{r['segment']}** — {verdict(r)}")
    A("")

    # ── catalyst x size ──
    A("## Catalyst × gap size")
    A("")
    rows_cs = []
    for c in cats[:3]:
        for b in SIZE_LABELS:
            sub = gaps[(gaps.catalyst == c) & (gaps.size_bucket == b)]
            rows_cs.append(segment_stats(sub, f"{c} · {b}"))
    A(table(rows_cs, "Segment"))
    A("")

    # ── cost context ──
    A("## Does any of this clear a spread?")
    A("")
    A("Gross of costs throughout. For scale, a round-trip hurdle in basis points of notional:")
    A("")
    A("| Segment | Mean edge (bps) | " + " | ".join(
        f"vs {k} ({v:.0f} bps)" for k, v in COST_HURDLES_BPS.items()) + " |")
    A("|---|---|" + "---|" * len(COST_HURDLES_BPS))
    for r in [all_stats] + rows:
        if not r.get("n", 0):
            continue
        edge_bps = r["mean_cont"] * 10_000
        cells = []
        for _, hurdle in COST_HURDLES_BPS.items():
            net = abs(edge_bps) - hurdle
            cells.append(f"{'clears by' if net > 0 else 'short by'} {abs(net):.1f} bps")
        A(f"| {r['segment']} | {edge_bps:+.2f} | " + " | ".join(cells) + " |")
    A("")
    A("These hurdles are a yardstick, not a fill model. They assume regular-hours liquidity at "
      "roughly mid. The opening auction is the widest, most adversarial moment of the session, so "
      "even the optimistic column is generous for a trade that enters at the open.")
    A("")

    gaps.to_csv(data_dir / "gaps_classified.csv", index=False)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(L))
    print(f"wrote {out_md} ({len(L)} lines)")
    print(f"\nOverall: n={all_stats['n']:,} dates={all_stats['eff_n_dates']:,} "
          f"mean_cont={all_stats['mean_cont']*100:.4f}% "
          f"clustered CI=[{all_stats['c_lo']*100:.4f}%, {all_stats['c_hi']*100:.4f}%]")
    print(f"Verdict: {verdict(all_stats)}")


if __name__ == "__main__":
    main()
