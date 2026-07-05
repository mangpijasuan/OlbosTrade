"""Tests for Chart Intelligence Phase 2: breakout, confirmation score, scanner."""

from app.services.chart.breakout_confirmation import (
    BreakoutInputs, ConfirmationRules, assess_breakout,
)
from app.services.chart.confirmation_score import ScoreInputs, compute_confirmation_score
from app.services.chart.setup_scanner import (
    SetupCandidate, rank_setups, strategy_fit_for,
)


# ── Breakout confirmation ────────────────────────────────────────────────────
def _bo(**kw):
    base = dict(kind="breakout", close=101.0, level=100.0, closed_bar=True,
                relative_volume=1.9, above_vwap=True, mtf_agrees=True, event_clear=True)
    base.update(kw)
    return assess_breakout(BreakoutInputs(**base))


def test_breakout_confirmed_when_all_gates_met():
    r = _bo()
    assert r.status == "confirmed"
    assert not r.pending_reasons
    assert any("closed above" in e for e in r.evidence)


def test_breakout_not_crossed_is_none():
    r = _bo(close=99.0)
    assert r.status == "none"


def test_breakout_detected_when_bar_not_closed():
    r = _bo(closed_bar=False)
    assert r.status == "detected"
    assert any("not closed" in p for p in r.pending_reasons)


def test_breakout_pending_on_low_volume():
    r = _bo(relative_volume=1.0)
    assert r.status == "detected"
    assert any("relative volume" in p for p in r.pending_reasons)


def test_breakout_pending_on_event():
    r = _bo(event_clear=False)
    assert r.status == "detected"
    assert any("event" in p for p in r.pending_reasons)


# ── Confirmation score ───────────────────────────────────────────────────────
def _score(**kw):
    base = dict(alignment_score=5.0, alignment_max=5.0, dominant="bullish",
                structure_agrees=True, breakout_confirmed=True, relative_volume=1.6,
                above_vwap=True, atr_pct=1.2, regime_fit=True, macro_risk="low",
                portfolio_overlap_pct=0.0, data_quality=85)
    base.update(kw)
    return compute_confirmation_score(ScoreInputs(**base))


def test_score_high_when_evidence_strong():
    r = _score()
    assert r.score >= 80
    assert r.supporting and not any("overlap" in x for x in r.risk_factors)


def test_score_penalised_by_macro():
    assert _score(macro_risk="very_high").score < _score(macro_risk="low").score


def test_score_penalised_by_overlap():
    r = _score(portfolio_overlap_pct=40.0)
    assert any("overlap" in x for x in r.risk_factors)


def test_score_is_evidence_not_probability():
    assert "not a calibrated probability" in _score().to_dict()["note"]


# ── Setup scanner ────────────────────────────────────────────────────────────
def _cand(symbol, score, bias="bullish", overlap=0.0, macro="low"):
    return SetupCandidate(
        symbol=symbol, bias=bias, confirmation_score=score, structure_state="uptrend",
        timeframe_alignment="4 of 5 bullish", macro_risk=macro,
        portfolio_overlap_pct=overlap, strategy_fit=["Momentum Swing"],
    )


def test_scanner_ranks_by_score_and_keeps_blocked():
    results = rank_setups([
        _cand("A", 85), _cand("B", 40), _cand("C", 90, overlap=50.0),
    ])
    assert [r.symbol for r in results] == ["C", "A", "B"]  # sorted by score desc
    c = next(r for r in results if r.symbol == "C")
    assert c.status == "blocked"                            # not hidden
    assert c.unblock_condition and any("overlap" in b for b in c.blocked_reasons)


def test_scanner_low_score_blocked_with_reason():
    r = rank_setups([_cand("B", 40)])[0]
    assert r.status == "blocked"
    assert any("below" in b for b in r.blocked_reasons)


def test_scanner_macro_high_is_caution_no_autopilot():
    r = rank_setups([_cand("A", 85, macro="high")])[0]
    assert r.status == "caution"
    assert "autopilot" not in r.modes_allowed


def test_scanner_eligible_all_modes():
    r = rank_setups([_cand("A", 85)])[0]
    assert r.status == "eligible"
    assert "autopilot" in r.modes_allowed


def test_strategy_fit():
    assert "Momentum Swing" in strategy_fit_for("bullish", "uptrend")
    assert strategy_fit_for("neutral", "range") == ["Wait for confirmation"]
