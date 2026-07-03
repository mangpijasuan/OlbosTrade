"""Tests for the CSP eligibility gate — the safety verdict layer."""

from app.services.csp_eligibility_gate import GateInputs, evaluate_eligibility


def _clean() -> GateInputs:
    """A fully eligible candidate — everything clear."""
    return GateInputs(
        kill_switch_engaged=False,
        guardrails_allowed=True,
        guardrails_reason=None,
        portfolio_overlap_pct=0.0,
        max_overlap_pct=25.0,
        assignment_level="low",
        earnings_level=None,
        macro_level="low",
        buying_power=24000.0,
        collateral_required=5800.0,
    )


def test_clean_candidate_is_eligible_all_modes():
    e = evaluate_eligibility(_clean())
    assert e.status == "eligible"
    assert set(e.modes_allowed) == {"manual", "copilot", "autopilot"}


def test_kill_switch_blocks_all_modes():
    inp = _clean()
    inp.kill_switch_engaged = True
    e = evaluate_eligibility(inp)
    assert e.status == "blocked"
    assert e.modes_allowed == []
    assert any("Kill switch" in r for r in e.blocked_reasons)
    assert e.unblock_condition


def test_guardrail_block_carries_reason():
    inp = _clean()
    inp.guardrails_allowed = False
    inp.guardrails_reason = "Daily loss limit reached"
    e = evaluate_eligibility(inp)
    assert e.status == "blocked"
    assert "Daily loss limit reached" in e.blocked_reasons


def test_insufficient_buying_power_blocks_with_actionable_unblock():
    inp = _clean()
    inp.buying_power = 1000.0  # < 5800 collateral
    e = evaluate_eligibility(inp)
    assert e.status == "blocked"
    assert e.unblock_condition and "buying power" in e.unblock_condition


def test_concentration_over_limit_blocks():
    inp = _clean()
    inp.portfolio_overlap_pct = 40.0  # > 25 limit
    e = evaluate_eligibility(inp)
    assert e.status == "blocked"
    assert any("exposure too high" in r for r in e.blocked_reasons)


def test_high_assignment_is_caution_not_blocked():
    inp = _clean()
    inp.assignment_level = "high"
    e = evaluate_eligibility(inp)
    assert e.status == "caution"
    assert e.modes_allowed == ["manual", "copilot"]  # autopilot excluded


def test_earnings_before_expiry_excludes_autopilot():
    inp = _clean()
    inp.earnings_level = "moderate"
    e = evaluate_eligibility(inp)
    assert e.status == "caution"
    assert "autopilot" not in e.modes_allowed


def test_hard_block_takes_precedence_over_caution():
    inp = _clean()
    inp.assignment_level = "high"       # would be caution
    inp.kill_switch_engaged = True       # but hard block wins
    e = evaluate_eligibility(inp)
    assert e.status == "blocked"
