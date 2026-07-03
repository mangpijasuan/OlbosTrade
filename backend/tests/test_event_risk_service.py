"""Tests for event-risk service. Macro logic is deterministic via injected as_of;
earnings lookups are monkeypatched to avoid network calls."""

from datetime import date

import app.services.event_risk_service as ers
from app.services.event_risk_service import assess_event_risk


def _no_earnings(monkeypatch):
    monkeypatch.setattr(ers, "_days_to_next_earnings", lambda ticker: None)


def test_macro_event_before_expiry_flagged_high(monkeypatch):
    _no_earnings(monkeypatch)
    # as_of one day before the 2026-01-28 FOMC → 1 day away, within a 30d expiry.
    risk = assess_event_risk("KO", dte=30, as_of=date(2026, 1, 27))
    assert risk.days_to_macro == 1
    assert risk.macro_flag.level == "high"
    assert risk.days_to_next_event == 1


def test_macro_event_after_expiry_is_low(monkeypatch):
    _no_earnings(monkeypatch)
    # Next macro (FOMC 2026-01-28) is 28 days out but option expires in 7 → no risk.
    risk = assess_event_risk("KO", dte=7, as_of=date(2025, 12, 31))
    assert risk.macro_flag.level == "low"
    assert risk.days_to_next_event is None


def test_earnings_before_expiry_flagged(monkeypatch):
    monkeypatch.setattr(ers, "_days_to_next_earnings", lambda ticker: 5)
    risk = assess_event_risk("PFE", dte=30, as_of=date(2025, 12, 1))
    assert risk.earnings_flag is not None
    assert risk.earnings_flag.level == "moderate"
    assert risk.days_to_next_event == 5


def test_earnings_after_expiry_not_flagged(monkeypatch):
    monkeypatch.setattr(ers, "_days_to_next_earnings", lambda ticker: 40)
    risk = assess_event_risk("PFE", dte=30, as_of=date(2025, 12, 1))
    assert risk.earnings_flag is None


def test_earnings_imminent_is_high(monkeypatch):
    monkeypatch.setattr(ers, "_days_to_next_earnings", lambda ticker: 1)
    risk = assess_event_risk("PFE", dte=30, as_of=date(2025, 12, 1))
    assert risk.earnings_flag.level == "high"


def test_nearest_event_wins_for_wqs(monkeypatch):
    # Earnings in 3d, macro FOMC 2026-01-28 from as_of 2026-01-20 = 8d.
    monkeypatch.setattr(ers, "_days_to_next_earnings", lambda ticker: 3)
    risk = assess_event_risk("PFE", dte=30, as_of=date(2026, 1, 20))
    assert risk.days_to_next_event == 3
