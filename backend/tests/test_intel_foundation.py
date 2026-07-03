"""Tests for the Intelligence Hub foundation: envelope, registry, why-moving."""

from datetime import datetime, timedelta, timezone

from app.services.intel.provider_base import (
    FilingProvider, NewsProvider, ProviderHealth, QualityStatus, make_envelope,
)
from app.services.intel.provider_registry import ProviderRegistry
from app.services.intel.why_moving import MoveInputs, explain_move


# ── DataEnvelope ─────────────────────────────────────────────────────────────
def test_envelope_freshness_and_serialization():
    past = datetime.now(timezone.utc) - timedelta(seconds=120)
    env = make_envelope({"x": 1}, source="TEST", as_of=past, confidence=0.5)
    assert env.freshness_seconds >= 119
    d = env.to_dict()
    assert d["source"] == "TEST" and d["confidence"] == 0.5
    assert d["is_delayed"] is True  # free/public data delayed by default


# ── Registry + data quality ──────────────────────────────────────────────────
class _FakeNews(NewsProvider):
    name = "FakeNews"
    def __init__(self, up: bool): self._up = up
    def health(self): return ProviderHealth(self.name, self._up)
    def fetch_news(self, symbol, limit=20): return []


class _FakeFilings(FilingProvider):
    name = "FakeEDGAR"
    def health(self): return ProviderHealth(self.name, True)
    def fetch_filings(self, symbol, limit=20): return []


def test_quality_score_full_stack():
    reg = ProviderRegistry()
    reg.register(_FakeNews(up=True))
    reg.register(_FakeFilings())
    rep = reg.data_quality("NVDA")
    # price_volume+earnings+options+filings+news = 25+15+15+15+15 = 85 (no macro)
    assert rep.score == 85
    assert "News feed" in rep.available
    assert "Macro data" in rep.unavailable
    assert any("Dark-pool" in u for u in rep.unavailable)


def test_quality_score_drops_when_provider_down():
    reg = ProviderRegistry()
    reg.register(_FakeNews(up=False))  # news provider unhealthy
    rep = reg.data_quality("NVDA")
    assert "News feed" in rep.unavailable
    assert rep.score < 85


def test_missing_baseline_lowers_score():
    reg = ProviderRegistry()
    rep = reg.data_quality("XYZ", has_options=False)
    assert "Options chain" in rep.unavailable


# ── Why is it moving? ────────────────────────────────────────────────────────
def test_why_moving_separates_facts_inference_unknown():
    r = explain_move(MoveInputs(
        symbol="NVDA", change_pct=4.2, relative_volume=2.8, vwap_relation="reclaimed",
        sector_change_pct=1.5, options_activity="elevated", days_to_earnings=8,
        atr_extension=1.8, news_detected=True,
    ))
    assert r.headline == "NVDA +4.2% today"
    assert any("2.8x" in f for f in r.facts)
    assert any("VWAP" in f for f in r.facts)
    assert r.inferences  # elevated volume / sector inference present
    assert any("Earnings in 8 days" in n for n in r.risk_notes)
    assert any("extended" in n for n in r.risk_notes)
    assert r.unknown  # always lists what we can't see


def test_why_moving_missing_inputs_go_to_unknown():
    r = explain_move(MoveInputs(symbol="ABC"))
    assert any("Relative volume unavailable" in u for u in r.unknown)
    assert any("No sourced news" in u for u in r.unknown)
    # No fabricated cause when we have nothing.
    assert r.headline == "ABC — move detected"


def test_why_moving_never_asserts_certainty():
    r = explain_move(MoveInputs(symbol="NVDA", change_pct=5.0, relative_volume=3.0))
    text = " ".join(r.inferences).lower()
    # Inferences are hedged ("suggests", "may"), never definitive causal claims.
    assert "suggests" in text or "may" in text
