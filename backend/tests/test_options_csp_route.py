"""Tests for the CSP screener route's pure assembly + the endpoint shape."""

from datetime import date

import app.services.event_risk_service as ers
from app.api.routes.options_csp import assemble_candidate


def _assemble(monkeypatch, **overrides):
    monkeypatch.setattr(ers, "_days_to_next_earnings", lambda ticker: None)
    base = dict(
        ticker="KO",
        stock_price=61.40,
        put_strike=58.0,
        delta=0.22,
        premium=0.74,
        dte=30,
        iv_rank=45.0,
        open_interest=1500,
        bid_ask_spread=0.04,
        risk_profile="balanced",
        portfolio_overlap_pct=0.0,
        max_overlap_pct=25.0,
        buying_power=24000.0,
        kill_switch_engaged=False,
        guardrails_allowed=True,
        guardrails_reason=None,
        as_of=date(2025, 12, 1),
    )
    base.update(overrides)
    return assemble_candidate(**base)


def test_clean_candidate_is_eligible(monkeypatch):
    c = _assemble(monkeypatch)
    assert c.eligibility.status == "eligible"
    assert "autopilot" in c.eligibility.modes_allowed
    assert c.collateral_required == 5800.0
    assert c.breakeven == 57.26
    assert c.wheel_quality_score > 0


def test_kill_switch_blocks(monkeypatch):
    c = _assemble(monkeypatch, kill_switch_engaged=True)
    assert c.eligibility.status == "blocked"
    assert c.eligibility.modes_allowed == []


def test_concentration_blocks_with_unblock(monkeypatch):
    c = _assemble(monkeypatch, portfolio_overlap_pct=40.0)
    assert c.eligibility.status == "blocked"
    assert c.eligibility.unblock_condition


def test_contributions_present_for_drawer(monkeypatch):
    c = _assemble(monkeypatch)
    assert set(c.wqs_contributions) == {
        "distance_to_strike", "liquidity", "event_free",
        "premium_yield", "iv_rank", "delta_in_band",
    }


def test_risk_flags_have_labels(monkeypatch):
    c = _assemble(monkeypatch)
    assert c.assignment_risk.label
    assert c.macro_event_risk.label


def test_endpoint_returns_wellformed_response(monkeypatch):
    """The route degrades gracefully to an empty, valid response when the live
    guardrail context is unavailable (fails closed)."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/options/csp/screen", json={"risk_profile": "balanced"})
    assert resp.status_code == 200
    body = resp.json()
    assert "context" in body and "candidates" in body
    assert body["context"]["risk_profile"] == "balanced"
    assert isinstance(body["candidates"], list)
