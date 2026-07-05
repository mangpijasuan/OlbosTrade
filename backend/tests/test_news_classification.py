"""Tests for News-to-Risk classification and Insider intelligence (deterministic)."""

from app.services.intel.news_classifier import classify
from app.services.intel.insider_intel import summarize_insider


# ── Classification ───────────────────────────────────────────────────────────
def test_earnings_beat_is_bullish_high():
    c = classify(title="Acme beats Q2 earnings, raises guidance")
    assert c.category == "Earnings"
    assert c.direction == "bullish"
    assert c.impact == "high"


def test_downgrade_is_bearish_analyst():
    c = classify(title="Analyst downgrade: price target cut on Acme")
    assert c.category == "Analyst"
    assert c.direction == "bearish"


def test_regulatory_lawsuit_high_bearish_blocks_new_entries():
    c = classify(title="SEC investigation and lawsuit filed against Acme")
    assert c.category == "Regulatory"
    assert c.impact == "high"
    assert c.direction == "bearish"
    assert c.risk_action == "block_new_entries"


def test_form4_filing_is_insider():
    c = classify(form_type="4", is_filing=True)
    assert c.category == "Insider"


def test_8k_is_corporate_action():
    c = classify(form_type="8-K", is_filing=True)
    assert c.category == "Corporate Action"


def test_uncertain_when_no_keywords():
    c = classify(title="Acme announces routine update")
    assert c.direction == "uncertain"
    assert any("uncertain" in l.lower() for l in c.limitations)


def test_mixed_direction():
    c = classify(title="Acme beats earnings but warns on weak guidance")
    assert c.direction == "mixed"


def test_classification_is_advisory_only():
    d = classify(title="Acme beats earnings").to_dict()
    assert d["advisory_only"] is True
    assert d["limitations"]


def test_confidence_bounded():
    c = classify(title="Acme surges on record buyback and upgrade")
    assert 0.2 <= c.confidence <= 0.95


# ── Insider intelligence ─────────────────────────────────────────────────────
def _filing(days_ago, form="4"):
    from datetime import datetime, timedelta, timezone
    return {"as_of": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
            "payload": {"form_type": form, "is_insider": form in ("3", "4", "5")}}


def test_insider_cluster_detected():
    s = summarize_insider("NVDA", [_filing(1), _filing(3), _filing(5), _filing(2)])
    assert s.insider_filings == 4
    assert s.cluster is True
    assert "Cluster" in s.context


def test_insider_no_cluster():
    s = summarize_insider("NVDA", [_filing(1), _filing(40)])
    assert s.cluster is False


def test_insider_ignores_non_insider_forms():
    s = summarize_insider("NVDA", [_filing(1, form="8-K"), _filing(2, form="4")])
    assert s.insider_filings == 1


def test_insider_states_limitations_and_research_only():
    d = summarize_insider("NVDA", [_filing(1)]).to_dict()
    assert d["research_only"] is True
    assert any("buy vs sell" in l for l in d["limitations"])
