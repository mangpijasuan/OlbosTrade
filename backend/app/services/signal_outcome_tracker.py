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
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ~1 trading month — roughly matches the horizon a 4xATR target (the
# equity trade plan's target distance) is expected to resolve within.
DEFAULT_MAX_HOLD_DAYS = 20


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
        from app.core.database import AsyncSessionLocal
        from app.models.signal_outcome import SignalOutcome

        indicators = signal.get("indicators") or {}
        generated_at_raw = signal.get("generated_at")
        try:
            generated_at = (
                datetime.fromisoformat(generated_at_raw)
                if generated_at_raw else datetime.now(timezone.utc)
            )
        except ValueError:
            generated_at = datetime.now(timezone.utc)

        row_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(SignalOutcome(
                    id=row_id,
                    signal_id=signal.get("id"),
                    ticker=signal.get("ticker", ""),
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


async def check_pending_outcomes(max_hold_days: int = DEFAULT_MAX_HOLD_DAYS) -> dict:
    """
    Resolve every pending signal against fresh daily bars, or expire it if
    max_hold_days trading bars pass with neither target nor stop hit.

    Returns a summary: {checked, target_hit, stop_hit, expired, still_pending}.
    """
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.signal_outcome import SignalOutcome

    summary = {"checked": 0, "target_hit": 0, "stop_hit": 0, "expired": 0, "still_pending": 0}

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

    for ticker, rows in by_ticker.items():
        earliest = min(r.generated_at for r in rows)
        try:
            hist = await _fetch_daily_bars(ticker, earliest)
        except Exception as exc:
            logger.warning("check_pending_outcomes: bars fetch failed for %s: %s", ticker, exc)
            continue
        if hist is None or hist.empty:
            continue

        for row in rows:
            summary["checked"] += 1
            resolution = _resolve_one(row, hist, max_hold_days)

            async with AsyncSessionLocal() as session:
                async with session.begin():
                    db_row = await session.get(SignalOutcome, row.id)
                    if db_row is None:
                        continue
                    db_row.checked_at = now
                    if resolution is None:
                        summary["still_pending"] += 1
                        continue
                    status, exit_price, resolved_at, days_elapsed, mfe_pct, mae_pct = resolution
                    summary[status] += 1
                    db_row.status = status
                    db_row.exit_price = Decimal(str(round(exit_price, 4)))
                    db_row.resolved_at = resolved_at
                    db_row.days_to_resolve = days_elapsed
                    db_row.max_favorable_pct = Decimal(str(round(mfe_pct, 4)))
                    db_row.max_adverse_pct = Decimal(str(round(mae_pct, 4)))

    return summary


# ── Stats aggregation (pure — no DB access) ─────────────────────────────────

CONFIDENCE_BUCKETS = [
    ("0.00-0.65", 0.0, 0.65),
    ("0.65-0.70", 0.65, 0.70),
    ("0.70-0.75", 0.70, 0.75),
    ("0.75-0.80", 0.75, 0.80),
    ("0.80-1.00", 0.80, 1.01),
]


def compute_signal_outcome_stats(outcomes: list[dict]) -> dict:
    """
    Aggregate hit rate / days-to-resolve stats from a list of outcome dicts
    (each with at least: status, confidence, days_to_resolve, ticker).

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

    return {
        "total": total,
        "pending": len(pending),
        "target_hit": len(target_hit),
        "stop_hit": len(stop_hit),
        "expired": len(expired),
        "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
        "avg_days_to_target": _avg_days(target_hit),
        "avg_days_to_stop": _avg_days(stop_hit),
        "by_confidence_bucket": by_confidence,
        "by_ticker": ticker_breakdown[:25],
    }
