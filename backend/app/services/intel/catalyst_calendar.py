"""
Event & Catalyst Calendar assembler.

Combines maintained macro events (from event_risk_service) with per-symbol
company events (earnings, via the existing yfinance path) into one severity-
ranked, timezone-aware feed for the UI. Read-only; it does not gate trades —
the existing event_risk_service.assess_event_risk remains the gate.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.event_risk_service import _days_to_next_earnings, list_macro_events

# Ordering for severity so the UI can sort "most important first".
_SEVERITY_RANK = {"very_high": 3, "high": 2, "moderate": 1, "low": 0}


def get_calendar(
    symbols: list[str] | None = None,
    days_ahead: int = 45,
    as_of: date | None = None,
) -> dict:
    """Return combined macro + company events within the window.

    Company events are best-effort per symbol (earnings only in Phase 1); a
    lookup failure yields no event for that symbol rather than an error."""
    today = as_of or datetime.now(timezone.utc).date()
    events: list[dict] = list(list_macro_events(as_of=today, days_ahead=days_ahead))

    for sym in (symbols or []):
        days = _days_to_next_earnings(sym)
        if days is None or days > days_ahead:
            continue
        severity = "high" if days <= 5 else "moderate"
        events.append({
            "name": f"{sym} earnings",
            "symbol": sym,
            "date": date.fromordinal(today.toordinal() + days).isoformat(),
            "days_away": days,
            "severity": severity,
            "kind": "earnings",
            "source": "yfinance calendar",
        })

    events.sort(key=lambda e: (e["days_away"], -_SEVERITY_RANK.get(e["severity"], 0)))
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "timezone": "America/New_York",
        "window_days": days_ahead,
        "events": events,
        "count": len(events),
    }
