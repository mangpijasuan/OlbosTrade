"""Tests for the Wheel Quality Score — verifies safety-tilt and profile-awareness."""

from app.services.wheel_quality_score import WqsInputs, score_candidate


def _safe_income_candidate() -> WqsInputs:
    """A liquid, well-OTM, event-free CSP with decent premium — the ideal."""
    return WqsInputs(
        stock_price=61.40,
        put_strike=58.0,          # ~5.5% OTM
        delta=0.22,               # in band
        premium=0.74,
        dte=30,
        iv_rank=45.0,
        open_interest=1500,
        bid_ask_spread=0.04,
        days_to_next_event=None,  # no earnings/macro
    )


def _risky_high_premium_candidate() -> WqsInputs:
    """Fat premium but close-to-money, illiquid, earnings before expiry."""
    return WqsInputs(
        stock_price=18.90,
        put_strike=18.0,          # ~4.8% OTM but high delta
        delta=0.42,               # outside band — assignment risk
        premium=0.95,             # rich
        dte=30,
        iv_rank=85.0,             # very rich IV
        open_interest=120,        # thin
        bid_ask_spread=0.28,      # wide
        days_to_next_event=10,    # earnings before expiry
    )


def test_score_is_bounded():
    result = score_candidate(_safe_income_candidate())
    assert 0.0 <= result.score <= 100.0


def test_contributions_sum_to_score():
    result = score_candidate(_safe_income_candidate())
    assert round(sum(result.contributions.values()), 1) == result.score


def test_safe_candidate_never_ranks_below_risky():
    """Capital-preservation guarantee: a dangerous trade never outranks a safe
    one. Safety-first profiles beat it outright; aggressive may close the gap
    (rich premium) but must never rank the risky trade higher."""
    safe = _safe_income_candidate()
    risky = _risky_high_premium_candidate()

    for profile in ("conservative", "balanced"):
        safe_score = score_candidate(safe, profile).score  # type: ignore[arg-type]
        risky_score = score_candidate(risky, profile).score  # type: ignore[arg-type]
        assert safe_score > risky_score, f"{profile}: safe {safe_score} !> risky {risky_score}"

    # Aggressive: the guarantee weakens to "never worse", not "strictly better".
    safe_agg = score_candidate(safe, "aggressive").score
    risky_agg = score_candidate(risky, "aggressive").score
    assert safe_agg >= risky_agg, f"aggressive: safe {safe_agg} < risky {risky_agg}"


def test_aggressive_rewards_the_risky_income_trade_more_than_conservative():
    """Same risky-but-rich trade should score higher under aggressive weighting."""
    risky = _risky_high_premium_candidate()
    conservative = score_candidate(risky, "conservative").score
    aggressive = score_candidate(risky, "aggressive").score
    assert aggressive > conservative


def test_event_before_expiry_penalized():
    base = _safe_income_candidate()
    with_event = WqsInputs(**{**base.__dict__, "days_to_next_event": 5})
    assert score_candidate(with_event).score < score_candidate(base).score


def test_explainability_factors_present():
    result = score_candidate(_safe_income_candidate())
    assert set(result.factors) == {
        "distance_to_strike", "liquidity", "event_free",
        "premium_yield", "iv_rank", "delta_in_band",
    }
