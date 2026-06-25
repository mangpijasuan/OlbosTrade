"""
US equity/options market-hours helper.

Used to gate order execution so the system only sends orders during regular
trading hours (RTH, 09:30–16:00 ET, Mon–Fri, excluding exchange holidays).
The app keeps running 24/7 (reconnects, classifies regime, generates signals);
only order submission is paused outside RTH and resumes automatically at the open.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)

# NYSE / OCC full-day holidays. Extend each year (or replace with a calendar lib).
_MARKET_HOLIDAYS = {
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Washington's Birthday
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
    # 2027
    "2027-01-01",
    "2027-01-18",
    "2027-02-15",
    "2027-03-26",
    "2027-05-31",
    "2027-06-18",  # Juneteenth (observed)
    "2027-07-05",  # Independence Day (observed)
    "2027-09-06",
    "2027-11-25",
    "2027-12-24",  # Christmas (observed)
}


def now_et(now: datetime | None = None) -> datetime:
    """Return the current time in US Eastern (or convert a supplied datetime)."""
    if now is None:
        return datetime.now(_ET)
    return now.astimezone(_ET) if now.tzinfo else now.replace(tzinfo=_ET)


def is_market_open(now: datetime | None = None) -> bool:
    """True only during regular trading hours on a trading day (ET)."""
    et = now_et(now)
    if et.weekday() >= 5:  # Saturday / Sunday
        return False
    if et.strftime("%Y-%m-%d") in _MARKET_HOLIDAYS:
        return False
    return RTH_OPEN <= et.time() < RTH_CLOSE


def market_status(now: datetime | None = None) -> dict:
    """Serialisable status for the UI / health checks."""
    et = now_et(now)
    is_open = is_market_open(et)
    if et.weekday() >= 5:
        reason = "weekend"
    elif et.strftime("%Y-%m-%d") in _MARKET_HOLIDAYS:
        reason = "holiday"
    elif et.time() < RTH_OPEN:
        reason = "pre_market"
    elif et.time() >= RTH_CLOSE:
        reason = "after_hours"
    else:
        reason = "open"
    return {
        "is_open": is_open,
        "reason": reason,
        "now_et": et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "rth": f"{RTH_OPEN.strftime('%H:%M')}-{RTH_CLOSE.strftime('%H:%M')} ET",
    }
