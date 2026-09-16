"""
Signal outcome tracker — persists every routable equity signal and checks
real forward price action against it.

record_signal() is called at signal-generation time (inside the equity
scanner's per-ticker loop, main.py::_run_equity_scan) so every BUY/SELL
signal that clears the routing threshold is captured — not just the ~15
that ever became actual trades. Trades alone are too small a sample and
selection-biased toward whatever already passed the confidence filter;
tracking every signal's real outcome is what lets hit rate and
days-to-target actually be measured, and eventually gives an ML pass
honest labels instead of backtest replay.

check_pending_outcomes() runs on a schedule (main.py's background loop)
and walks forward daily bars for each still-pending signal to see whether
price reached its target before its stop, or neither within the hold
window.

One signal per (ticker, action, day)
------------------------------------
The scanner re-evaluates the whole watchlist every tick, so without a guard
the *same* setup is recorded again on each pass. Measured in the 2026-08-28
assessment: 70,798 rows representing roughly 1,568 real (ticker, action, day)
signals — about 45x duplication. That is not merely wasted rows:

  - it made the dataset look ~45x larger than it is, which is how a
    ~1,568-signal sample reads as 70k;
  - it blew the resolver's time budget (~65k rows against a 120s scheduler
    limit), so check_pending_outcomes() was killed mid-pass every run and
    left a labelled subset selected by DB iteration order — which, as that
    investigation noted, "reads exactly like real data."

record_signal() therefore keeps the FIRST signal per (ticker, action, day)
and returns that row's id for later re-emissions. First is the right one to
keep: it is the moment the setup actually became actionable, before the day's
price action moved the entry/stop/target under it.

There is deliberately no UNIQUE constraint backing this yet — ~69k historical
duplicates still exist, so adding one would make the next `alembic upgrade
head` (and therefore deploy/hetzner/update.sh) fail. Run
scripts/dedupe_signal_outcomes.py first; the index can follow once history is
clean.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ~1 trading month — roughly matches the horizon a 4xATR target (the
# equity trade plan's target distance) is expected to resolve within.
# How long a signal gets to reach target or stop before it is closed as
# "expired". Settings-driven for the same reason as the ATR multipliers: it
# and the target distance are one decision, not two. A target the signal
# cannot reach inside this window does not become a loss, it becomes an
# expiry — and because `hit_rate` excludes expiries from its denominator,
# that silently removes would-be winners from the measurement rather than
# showing up as a worse number. See config.py.
DEFAULT_MAX_HOLD_DAYS = settings.signal_max_hold_days

# Rows per UPDATE statement, and how many accumulate before a flush. Chunking
# keeps a single pass from building one enormous statement or holding the whole
# backlog in memory, while staying far away from the per-row transaction cost
# that stalled this job.
_WRITE_CHUNK = 1000
_FLUSH_EVERY = 5000


def _dec_or_none(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(round(float(value), 4)))
    except (TypeError, ValueError):
        return None


async def record_signal(signal: dict) -> Optional[str]:
    """
    Persist a routable equity BUY/SELL signal for forward-outcome tracking.

    No-ops (returns None) for HOLD signals or signals without a usable
    trade_plan — there's nothing to track a target/stop against. Never
    raises: a tracking failure must not break the scan that produced the
    signal.
    """
    action = signal.get("action")
    if action not in ("BUY", "SELL"):
        return None

    trade_plan = signal.get("trade_plan") or {}
    entry = trade_plan.get("entry_price")
    stop = trade_plan.get("stop_price")
    target = trade_plan.get("target_price")
    if not entry or not stop or not target:
        return None

    try:
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.models.signal_outcome import SignalOutcome
        from app.services.equity_signal_engine import EQUITY_SCORING_VERSION

        indicators = signal.get("indicators") or {}

        # The scan loop sets signal["opportunity_score"] before calling here
        # (main.py, immediately after building the signal dict), so this is a
        # read of something already computed — no extra work, no extra I/O.
        #
        # Only the composite and its liquidity/regime components are kept. The
        # other three weights are confidence-determined (see the model's own
        # comment), and the Alpha Edge entry score and risk score are exact
        # monotone transforms of `confidence`, so storing them would re-express
        # a column that is already two lines below this one.
        oppty = signal.get("opportunity_score")
        oppty_score = None
        oppty_components: dict = {}
        if isinstance(oppty, dict):
            raw_score = oppty.get("score")
            if isinstance(raw_score, (int, float)):
                oppty_score = int(round(raw_score))
            oppty_components = oppty.get("components") or {}

        generated_at_raw = signal.get("generated_at")
        try:
            generated_at = (
                datetime.fromisoformat(generated_at_raw)
                if generated_at_raw else datetime.now(timezone.utc)
            )
        except ValueError:
            generated_at = datetime.now(timezone.utc)

        # Normalize to UTC before deriving the day boundary — a `generated_at`
        # parsed from an offset-less string comes back naive, and treating that
        # as local time would put the window on the wrong day.
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        else:
            generated_at = generated_at.astimezone(timezone.utc)

        ticker = signal.get("ticker", "")
        row_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            # One row per (ticker, action, UTC day) — see the module docstring.
            # Expressed as a half-open range rather than date(generated_at) so
            # it uses idx_signal_outcomes_generated_at and carries no dependence
            # on the session's timezone setting.
            day_start = generated_at.replace(hour=0, minute=0, second=0, microsecond=0)
            existing_id = (await session.execute(
                select(SignalOutcome.id)
                .where(
                    SignalOutcome.ticker == ticker,
                    SignalOutcome.asset_type == "equity",
                    SignalOutcome.action == action,
                    SignalOutcome.generated_at >= day_start,
                    SignalOutcome.generated_at < day_start + timedelta(days=1),
                )
                .limit(1)
            )).scalar_one_or_none()
            if existing_id is not None:
                logger.debug(
                    "record_signal: %s %s already recorded for %s — keeping the first",
                    ticker, action, day_start.date(),
                )
                return str(existing_id)

            async with session.begin():
                session.add(SignalOutcome(
                    id=row_id,
                    signal_id=signal.get("id"),
                    ticker=ticker,
                    asset_type="equity",
                    action=action,
                    confidence=Decimal(str(round(signal.get("confidence", 0.0), 4))),
                    entry_price=Decimal(str(round(float(entry), 4))),
                    stop_price=Decimal(str(round(float(stop), 4))),
                    target_price=Decimal(str(round(float(target), 4))),
                    target_move_pct=_dec_or_none(trade_plan.get("target_move_pct")),
                    generated_at=generated_at,
                    status="pending",
                    rsi=_dec_or_none(indicators.get("rsi")),
                    macd=_dec_or_none(indicators.get("macd")),
                    bb_pct_b=_dec_or_none(indicators.get("bb_pct_b")),
                    volume_ratio=_dec_or_none(indicators.get("volume_ratio")),
                    atr=_dec_or_none(indicators.get("atr")),
                    regime=signal.get("regime"),
                    signal_engine_version=EQUITY_SCORING_VERSION,
                    opportunity_score=oppty_score,
                    oppty_liquidity=_dec_or_none(oppty_components.get("liquidity")),
                    oppty_regime=_dec_or_none(oppty_components.get("regime")),
                ))
        return str(row_id)
    except Exception as exc:
        logger.warning("record_signal failed for %s: %s", signal.get("ticker"), exc)
        return None


async def _fetch_daily_bars(ticker: str, start: datetime):
    """Fetch daily OHLC bars for ticker from `start` through today."""
    import asyncio
    import yfinance as yf

    loop = asyncio.get_running_loop()

    def _fetch():
        period_days = max((datetime.now(timezone.utc) - start).days + 5, 10)
        return yf.Ticker(ticker).history(period=f"{period_days}d", auto_adjust=True)

    return await loop.run_in_executor(None, _fetch)


def _to_utc(ts) -> datetime:
    dt = ts.to_pydatetime()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_one(row, hist, max_hold_days: int):
    """
    Walk bars strictly after the signal's own entry day, checking each
    day's high/low against target and stop.

    When both target and stop are crossed on the same bar, the stop wins —
    a conservative tie-break rather than assuming the best case for a day
    we only have a high/low/close for, not an intraday path.

    Returns (status, exit_price, resolved_at, days_elapsed, mfe_pct,
    mae_pct) or None if still unresolved within the bars available.
    """
    entry_date = row.generated_at.date()
    action = row.action
    entry = float(row.entry_price)
    stop = float(row.stop_price)
    target = float(row.target_price)

    mfe_pct = 0.0
    mae_pct = 0.0
    days_elapsed = 0

    for ts, bar in hist.iterrows():
        bar_date = ts.date() if hasattr(ts, "date") else ts
        if bar_date <= entry_date:
            continue
        days_elapsed += 1
        high, low, close = float(bar["High"]), float(bar["Low"]), float(bar["Close"])

        if action == "BUY":
            fav, adv = (high - entry) / entry, (low - entry) / entry
            stop_hit, target_hit = low <= stop, high >= target
        else:
            fav, adv = (entry - low) / entry, (entry - high) / entry
            stop_hit, target_hit = high >= stop, low <= target

        mfe_pct = max(mfe_pct, fav)
        mae_pct = min(mae_pct, adv)

        if stop_hit:
            return "stop_hit", stop, _to_utc(ts), days_elapsed, mfe_pct, mae_pct
        if target_hit:
            return "target_hit", target, _to_utc(ts), days_elapsed, mfe_pct, mae_pct
        if days_elapsed >= max_hold_days:
            return "expired", close, _to_utc(ts), days_elapsed, mfe_pct, mae_pct

    return None


async def check_pending_outcomes(
    max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
    deadline_seconds: Optional[float] = None,
) -> dict:
    """
    Resolve every pending signal against fresh daily bars, or expire it if
    max_hold_days trading bars pass with neither target nor stop hit.

    Returns a summary: {checked, target_hit, stop_hit, expired, still_pending,
    tickers_covered, tickers_total, truncated, oldest_pending_age_days,
    elapsed_s}.

    On coverage, and why this function is shaped the way it is
    ---------------------------------------------------------
    These rows are the training labels for anything that later learns from
    signal outcomes, so *which* signals get resolved has to be a property of
    the signals, never of how far the job happened to get. The previous
    implementation opened a fresh session and transaction per row and wrote
    `checked_at` on every pending row each pass — so a backlog of ~65k rows
    meant ~65k transactions per run against a 120s scheduler budget, and the
    job was killed mid-pass every time (confirmed in production 2026-08-27/28:
    two consecutive `timed out after 120s` errors, and only 32 of 102 tickers
    had ever received a single label — the other 70 had none at all).

    That silent truncation is worse than a slow job: it produced a labelled
    subset selected by DB iteration order and the position of the timeout,
    which reads exactly like real data and is not. Three changes address it:

    * **Batched writes.** Same-value `checked_at` stamps collapse into one
      UPDATE per chunk, and resolutions go out as a single executemany —
      turning ~65k transactions into a handful.
    * **Oldest-first ticker order.** Tickers are processed by their oldest
      pending signal, so a run that cannot finish still drains the longest
      backlog instead of re-walking whichever tickers sort first.
    * **An owned deadline.** The caller passes a budget and the job stops at a
      ticker boundary, flushes, and reports `truncated=True`. Being cancelled
      externally mid-write is what made the shortfall invisible before.
    """
    import time as _time

    from sqlalchemy import select, update
    from app.core.database import AsyncSessionLocal
    from app.models.signal_outcome import SignalOutcome

    started = _time.monotonic()
    summary = {
        "checked": 0, "target_hit": 0, "stop_hit": 0, "expired": 0,
        "still_pending": 0, "tickers_covered": 0, "tickers_total": 0,
        "truncated": False, "oldest_pending_age_days": None, "elapsed_s": 0.0,
    }

    async with AsyncSessionLocal() as session:
        pending = (await session.execute(
            select(SignalOutcome).where(SignalOutcome.status == "pending")
        )).scalars().all()

    if not pending:
        return summary

    by_ticker: dict[str, list] = {}
    for row in pending:
        by_ticker.setdefault(row.ticker, []).append(row)

    now = datetime.now(timezone.utc)
    summary["tickers_total"] = len(by_ticker)
    oldest = min(r.generated_at for r in pending)
    summary["oldest_pending_age_days"] = (now - oldest).days

    # Oldest backlog first — see docstring. Ticker name breaks ties so a run
    # is reproducible rather than depending on dict/query ordering.
    ordered = sorted(by_ticker.items(),
                     key=lambda kv: (min(r.generated_at for r in kv[1]), kv[0]))

    resolved_payloads: list[dict] = []
    checked_ids: list = []

    async def _flush() -> None:
        """Write everything accumulated so far. Safe to call repeatedly."""
        if not resolved_payloads and not checked_ids:
            return
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # One statement per chunk: every row gets the same timestamp,
                # so there is nothing per-row to bind.
                for i in range(0, len(checked_ids), _WRITE_CHUNK):
                    await session.execute(
                        update(SignalOutcome)
                        .where(SignalOutcome.id.in_(checked_ids[i:i + _WRITE_CHUNK]))
                        .values(checked_at=now)
                    )
                # Resolutions differ per row, so this is an executemany keyed
                # on the primary key rather than one statement per row.
                for i in range(0, len(resolved_payloads), _WRITE_CHUNK):
                    await session.execute(
                        update(SignalOutcome), resolved_payloads[i:i + _WRITE_CHUNK]
                    )
        resolved_payloads.clear()
        checked_ids.clear()

    for ticker, rows in ordered:
        if deadline_seconds is not None and _time.monotonic() - started >= deadline_seconds:
            summary["truncated"] = True
            break

        try:
            earliest = min(r.generated_at for r in rows)
            hist = await _fetch_daily_bars(ticker, earliest)
        except Exception as exc:
            logger.warning("check_pending_outcomes: bars fetch failed for %s: %s", ticker, exc)
            continue
        if hist is None or hist.empty:
            continue

        summary["tickers_covered"] += 1

        for row in rows:
            summary["checked"] += 1
            checked_ids.append(row.id)
            resolution = _resolve_one(row, hist, max_hold_days)
            if resolution is None:
                summary["still_pending"] += 1
                continue
            status, exit_price, resolved_at, days_elapsed, mfe_pct, mae_pct = resolution
            summary[status] += 1
            resolved_payloads.append({
                "id": row.id,
                "status": status,
                "exit_price": Decimal(str(round(exit_price, 4))),
                "resolved_at": resolved_at,
                "days_to_resolve": days_elapsed,
                "max_favorable_pct": Decimal(str(round(mfe_pct, 4))),
                "max_adverse_pct": Decimal(str(round(mae_pct, 4))),
            })

        if len(checked_ids) >= _FLUSH_EVERY:
            await _flush()

    await _flush()
    summary["elapsed_s"] = round(_time.monotonic() - started, 1)

    # Partial coverage must be loud. A truncated pass leaves a biased label
    # set behind, and the whole point of this rewrite is that such a pass can
    # never again look identical to a complete one.
    if summary["truncated"] or summary["tickers_covered"] < summary["tickers_total"]:
        logger.warning(
            "check_pending_outcomes covered %d/%d tickers in %.1fs (truncated=%s) — "
            "labels are INCOMPLETE; oldest pending signal is %s days old",
            summary["tickers_covered"], summary["tickers_total"],
            summary["elapsed_s"], summary["truncated"],
            summary["oldest_pending_age_days"],
        )

    return summary


# ── Stats aggregation (pure — no DB access) ─────────────────────────────────

CONFIDENCE_BUCKETS = [
    ("0.00-0.65", 0.0, 0.65),
    ("0.65-0.70", 0.65, 0.70),
    ("0.70-0.75", 0.70, 0.75),
    ("0.75-0.80", 0.75, 0.80),
    ("0.80-1.00", 0.80, 1.01),
]


def _confidence_buckets(outcomes: list[dict]) -> dict:
    """Factored out so both the top-level result and the by_regime
    breakdown reuse the exact same bucketing, not a second copy of it."""
    by_confidence = {}
    for label, lo, hi in CONFIDENCE_BUCKETS:
        bucket = [o for o in outcomes if lo <= float(o["confidence"]) < hi]
        b_target = [o for o in bucket if o["status"] == "target_hit"]
        b_stop = [o for o in bucket if o["status"] == "stop_hit"]
        b_decisive = len(b_target) + len(b_stop)
        by_confidence[label] = {
            "count": len(bucket),
            "hit_rate": round(len(b_target) / b_decisive, 3) if b_decisive > 0 else None,
        }
    return by_confidence


# ── R-based outcome maths ────────────────────────────────────────────────
#
# R is one unit of risk: the entry-to-stop distance. Everything below is in
# R rather than ATR or percent, so it stays comparable across tickers AND
# across changes to the multipliers themselves — a 4×ATR target over a 2×ATR
# stop is 2.0R, and it is still 2.0R after both multipliers are halved.
#
# Why this exists at all: `hit_rate` cannot answer "is the target in the
# right place". It excludes expiries, and expiry is not neutral — the stop is
# nearer than the target, so slow winners expire while losers resolve, and
# the excluded pile is disproportionately made of signals that would have
# won. These functions measure the signals themselves instead of the
# subset that happened to resolve decisively.

def _risk_per_share(o: dict) -> Optional[float]:
    """1R in price terms. None when the row cannot support the maths."""
    entry, stop = o.get("entry_price"), o.get("stop_price")
    if entry is None or stop is None:
        return None
    risk = abs(float(entry) - float(stop))
    return risk if risk > 0 else None


def _realised_r(o: dict) -> Optional[float]:
    """What the signal actually returned, in R, signed for its direction."""
    risk = _risk_per_share(o)
    exit_price, entry = o.get("exit_price"), o.get("entry_price")
    if risk is None or exit_price is None or entry is None:
        return None
    move = float(exit_price) - float(entry)
    if str(o.get("action", "")).upper() == "SELL":
        move = -move
    return move / risk


def _mfe_r(o: dict) -> Optional[float]:
    """Max favourable excursion in R — how far it went before it turned.

    max_favorable_pct is a fraction OF ENTRY (see _resolve_one), so it has to
    be taken back to price before it can be divided by risk.
    """
    risk = _risk_per_share(o)
    mfe, entry = o.get("max_favorable_pct"), o.get("entry_price")
    if risk is None or mfe is None or entry is None:
        return None
    return (float(mfe) * float(entry)) / risk


def _target_distance_r(o: dict) -> Optional[float]:
    """Where the target sits, in R. 4×ATR over a 2×ATR stop is 2.0R."""
    risk = _risk_per_share(o)
    target, entry = o.get("target_price"), o.get("entry_price")
    if risk is None or target is None or entry is None:
        return None
    return abs(float(target) - float(entry)) / risk


MFE_BUCKETS_R = [
    ("0.0-0.5R", 0.0, 0.5),
    ("0.5-1.0R", 0.5, 1.0),
    ("1.0-1.5R", 1.0, 1.5),
    ("1.5-2.0R", 1.5, 2.0),
    ("2.0-3.0R", 2.0, 3.0),
    ("3.0R+",    3.0, float("inf")),
]

# Candidate target distances to report a counterfactual expectancy for.
CANDIDATE_TARGETS_R = [1.0, 1.5, 2.0, 2.5, 3.0]


def _counterfactual_expectancy(outcomes: list[dict], target_r: float) -> Optional[float]:
    """Roughly what expectancy would have been with the target at `target_r`.

    READ THE CAVEAT. Bar data records how far a signal went, not WHEN, so for
    a signal that ended at its stop having first run past `target_r`, this
    cannot tell whether the favourable excursion came before the stop or
    after it. It assumes before, which makes every number here an OPTIMISTIC
    bound, and most optimistic for small target_r where more stopped-out rows
    qualify.

    So this ranks candidates and says which are worth testing properly. It is
    not a backtest and must not be quoted as an expected return.
    """
    rows = []
    for o in outcomes:
        if o.get("status") == "pending":
            continue
        mfe, realised = _mfe_r(o), _realised_r(o)
        if mfe is None or realised is None:
            continue
        rows.append(target_r if mfe >= target_r else realised)
    return round(sum(rows) / len(rows), 3) if rows else None


def compute_signal_outcome_stats(outcomes: list[dict]) -> dict:
    """
    Aggregate hit rate / days-to-resolve stats from a list of outcome dicts
    (each with at least: status, confidence, days_to_resolve, ticker,
    regime).

    hit_rate excludes "expired" and "pending" from the denominator — it
    answers "of the signals that actually resolved one way or the other,
    how many hit target before stop", not "of everything ever generated".
    """
    total = len(outcomes)
    pending = [o for o in outcomes if o["status"] == "pending"]
    target_hit = [o for o in outcomes if o["status"] == "target_hit"]
    stop_hit = [o for o in outcomes if o["status"] == "stop_hit"]
    expired = [o for o in outcomes if o["status"] == "expired"]

    resolved_decisive = len(target_hit) + len(stop_hit)
    hit_rate = (len(target_hit) / resolved_decisive) if resolved_decisive > 0 else None

    def _avg_days(rows: list[dict]) -> Optional[float]:
        days = [r["days_to_resolve"] for r in rows if r.get("days_to_resolve") is not None]
        return round(sum(days) / len(days), 1) if days else None

    by_ticker: dict[str, dict] = {}
    for o in outcomes:
        t = o["ticker"]
        by_ticker.setdefault(t, {"total": 0, "target_hit": 0, "stop_hit": 0})
        by_ticker[t]["total"] += 1
        if o["status"] in ("target_hit", "stop_hit"):
            by_ticker[t][o["status"]] += 1
    ticker_breakdown = []
    for t, s in by_ticker.items():
        decisive = s["target_hit"] + s["stop_hit"]
        ticker_breakdown.append({
            "ticker": t,
            "total": s["total"],
            "hit_rate": round(s["target_hit"] / decisive, 3) if decisive > 0 else None,
        })
    ticker_breakdown.sort(key=lambda x: x["total"], reverse=True)

    by_confidence = _confidence_buckets(outcomes)

    regimes = sorted({o.get("regime") for o in outcomes if o.get("regime")})
    by_regime = {
        r: _confidence_buckets([o for o in outcomes if o.get("regime") == r])
        for r in regimes
    }

    # ── Is the target in the right place? ────────────────────────────
    # hit_rate cannot answer that: it drops expiries, and expiry is not
    # neutral between winners and losers. These are measured over every
    # RESOLVED signal, expiries included, so nothing is silently excluded.
    resolved = [o for o in outcomes if o["status"] != "pending"]
    realised = [r for r in (_realised_r(o) for o in resolved) if r is not None]
    mfes = [m for m in (_mfe_r(o) for o in resolved) if m is not None]
    target_rs = [t for t in (_target_distance_r(o) for o in outcomes)
                 if t is not None]

    by_mfe_bucket = {}
    for label, lo, hi in MFE_BUCKETS_R:
        by_mfe_bucket[label] = sum(1 for m in mfes if lo <= m < hi)

    # The headline: mean R per resolved signal. Positive means the system
    # makes money, whatever the hit rate says. A 2R target reached a third of
    # the time and a 1R loss the rest is expectancy 0 — hit rate alone never
    # shows that.
    expectancy_r = round(sum(realised) / len(realised), 3) if realised else None

    return {
        "total": total,
        "pending": len(pending),
        "target_hit": len(target_hit),
        "stop_hit": len(stop_hit),
        "expired": len(expired),
        "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
        "expectancy_r": expectancy_r,
        "resolved_with_r": len(realised),
        "target_distance_r": round(sum(target_rs) / len(target_rs), 2) if target_rs else None,
        "mfe_r_median": round(sorted(mfes)[len(mfes) // 2], 2) if mfes else None,
        "by_mfe_bucket_r": by_mfe_bucket,
        "counterfactual_expectancy_r": {
            str(t): _counterfactual_expectancy(resolved, t)
            for t in CANDIDATE_TARGETS_R
        },
        "avg_days_to_target": _avg_days(target_hit),
        "avg_days_to_stop": _avg_days(stop_hit),
        "by_confidence_bucket": by_confidence,
        "by_regime": by_regime,
        "by_ticker": ticker_breakdown[:25],
    }
