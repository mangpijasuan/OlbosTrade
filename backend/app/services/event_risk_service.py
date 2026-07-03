"""
Event-risk service — how close is a market-moving event before option expiry?

Two sources:
  * Earnings — per-ticker, via yfinance (same source as equity_signal_engine's
    earnings_gate; results cached 1h).
  * Macro — a maintained schedule of high-impact US events (FOMC, CPI, NFP).
    FOMC dates are published a year ahead, so a static table is accurate and
    dependency-free. Update _MACRO_CALENDAR once a year.

Produces the RiskFlag shape (level / label / detail) consumed by the CSP
screener contract, and the integer days_to_next_event that feeds
wheel_quality_score.

Design: fail-OPEN on data errors for the informational flag (never crash a
screen), but the eligibility gate — not this service — makes the block/allow
decision. This only surfaces risk; it does not authorize trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from app.utils.logger import get_logger

logger = get_logger(__name__)

RiskLevel = Literal["low", "moderate", "high", "unavailable"]


@dataclass
class RiskFlag:
    level: RiskLevel
    label: str
    detail: str


@dataclass
class EventRisk:
    """Combined earnings + macro assessment for one candidate."""

    days_to_earnings: int | None
    days_to_macro: int | None
    earnings_flag: RiskFlag | None
    macro_flag: RiskFlag
    # Nearest event of any kind within the option's life — feeds WQS.
    days_to_next_event: int | None


# High-impact US macro events. Maintain annually — FOMC decision dates and the
# BLS CPI / jobs-report schedule are published well in advance.
# (Representative 2026 dates; verify against the official calendars each year.)
_MACRO_CALENDAR: list[tuple[date, str]] = [
    (date(2026, 1, 28), "FOMC"),
    (date(2026, 2, 11), "CPI"),
    (date(2026, 3, 6), "NFP"),
    (date(2026, 3, 18), "FOMC"),
    (date(2026, 4, 10), "CPI"),
    (date(2026, 5, 6), "FOMC"),
    (date(2026, 6, 17), "FOMC"),
    (date(2026, 7, 15), "CPI"),
    (date(2026, 7, 29), "FOMC"),
    (date(2026, 8, 7), "NFP"),
    (date(2026, 9, 16), "FOMC"),
    (date(2026, 10, 28), "FOMC"),
    (date(2026, 12, 9), "FOMC"),
]

# Severity per macro event type — feeds the calendar UI and event-risk windows.
_MACRO_SEVERITY: dict[str, str] = {
    "FOMC": "very_high",
    "CPI": "high",
    "PPI": "high",
    "NFP": "high",
    "PCE": "moderate",
    "GDP": "moderate",
}


def list_macro_events(as_of: date | None = None, days_ahead: int = 45) -> list[dict]:
    """Upcoming high-impact macro events within the window, with severity.

    Read-only accessor for the calendar UI. Does not affect the risk gate."""
    today = as_of or datetime.now(timezone.utc).date()
    horizon = today.toordinal() + days_ahead
    out: list[dict] = []
    for event_date, name in sorted(_MACRO_CALENDAR):
        if event_date < today or event_date.toordinal() > horizon:
            continue
        out.append({
            "name": name,
            "date": event_date.isoformat(),
            "days_away": (event_date - today).days,
            "severity": _MACRO_SEVERITY.get(name, "moderate"),
            "kind": "macro",
            "source": "maintained macro calendar",
        })
    return out


_earnings_cache: dict[str, tuple[int | None, datetime]] = {}
_CACHE_TTL_SECONDS = 3600


def _days_to_next_earnings(ticker: str) -> int | None:
    """Days until the next earnings date (>=0), or None if unknown/none upcoming.

    Reuses the yfinance calendar approach from equity_signal_engine.earnings_gate,
    but returns the day count instead of a boolean gate.
    """
    now = datetime.now(timezone.utc)
    if ticker in _earnings_cache:
        cached_days, cached_at = _earnings_cache[ticker]
        if (now - cached_at).total_seconds() < _CACHE_TTL_SECONDS:
            return cached_days

    result: int | None = None
    try:
        import pandas as pd  # type: ignore
        import yfinance as yf  # type: ignore

        cal = yf.Ticker(ticker).calendar
        earn_dates: list = []
        if isinstance(cal, dict):
            earn_dates = cal.get("Earnings Date", []) or []
        elif cal is not None:
            try:
                if not cal.empty and "Earnings Date" in cal.index:
                    earn_dates = list(cal.loc["Earnings Date"])
            except Exception:
                pass

        upcoming: list[int] = []
        for val in earn_dates:
            try:
                ts = pd.Timestamp(val)
                ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
                days_away = (ts - pd.Timestamp(now)).days
                if days_away >= 0:
                    upcoming.append(days_away)
            except Exception:
                continue
        if upcoming:
            result = min(upcoming)
    except Exception as exc:
        logger.warning("Earnings lookup failed for %s: %s", ticker, exc)
        _earnings_cache[ticker] = (None, now)
        return None

    _earnings_cache[ticker] = (result, now)
    return result


def _days_to_next_macro(as_of: date | None = None) -> tuple[int | None, str | None]:
    """Days until the next high-impact macro event, plus its name."""
    today = as_of or datetime.now(timezone.utc).date()
    future = sorted((d, name) for d, name in _MACRO_CALENDAR if d >= today)
    if not future:
        return None, None
    event_date, name = future[0]
    return (event_date - today).days, name


def _earnings_flag(days: int | None, dte: int) -> RiskFlag | None:
    if days is None:
        return None
    if days >= dte:
        return None  # earnings falls after expiry — no risk to this trade
    if days <= 2:
        return RiskFlag("high", "Earnings imminent", f"Earnings in {days}d, before expiry")
    return RiskFlag("moderate", f"Earnings {days}d", f"Earnings in {days}d, before {dte}d expiry")


def _macro_flag(days: int | None, name: str | None, dte: int) -> RiskFlag:
    if days is None or name is None or days > dte:
        return RiskFlag("low", "No macro event", "No high-impact macro event before expiry")
    if days <= 2:
        return RiskFlag("high", f"{name} in {days}d", f"High-impact {name} in {days}d, before expiry")
    return RiskFlag("moderate", f"{name} {days}d", f"{name} in {days}d, before {dte}d expiry")


def assess_event_risk(ticker: str, dte: int, as_of: date | None = None) -> EventRisk:
    """Combined earnings + macro event risk for a candidate expiring in `dte` days."""
    days_earn = _days_to_next_earnings(ticker)
    days_macro, macro_name = _days_to_next_macro(as_of)

    earnings_flag = _earnings_flag(days_earn, dte)
    macro_flag = _macro_flag(days_macro, macro_name, dte)

    # Nearest event that lands within the option's life feeds WQS.
    within_life = [
        d for d in (days_earn, days_macro)
        if d is not None and d < dte
    ]
    days_to_next_event = min(within_life) if within_life else None

    return EventRisk(
        days_to_earnings=days_earn,
        days_to_macro=days_macro,
        earnings_flag=earnings_flag,
        macro_flag=macro_flag,
        days_to_next_event=days_to_next_event,
    )
