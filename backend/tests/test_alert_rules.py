"""Tests for the Smart Alerts rule engine — including the no-order safety invariant."""

from app.services.alerts.rule_engine import (
    Predicate, Rule, evaluate_rules, route_outcome,
)


def _rule(preds, mode="manual", enabled=True):
    return Rule("r1", "Test", "QQQ", preds, mode=mode, enabled=enabled)


# ── Predicate evaluation ─────────────────────────────────────────────────────
def test_predicate_numeric_ops():
    snap = {"relative_volume": 1.9}
    assert Predicate("relative_volume", "gt", 1.8).evaluate(snap)
    assert not Predicate("relative_volume", "gt", 2.0).evaluate(snap)
    assert Predicate("relative_volume", "gte", 1.9).evaluate(snap)


def test_predicate_missing_metric_fails():
    assert not Predicate("nonexistent", "gt", 1).evaluate({"x": 5})


def test_predicate_none_value_fails():
    assert not Predicate("iv", "gt", 1).evaluate({"iv": None})


def test_predicate_contains_and_bool():
    assert Predicate("regime", "contains", "trending").evaluate({"regime": "low_vol_trending"})
    assert Predicate("above_vwap", "is_true", None).evaluate({"above_vwap": True})
    assert Predicate("above_vwap", "is_false", None).evaluate({"above_vwap": False})


def test_predicate_within_for_event_window():
    # minutes-to-event <= 60 should NOT fire the "no event within 60m" style rule;
    # here `within` means "actual <= value".
    assert Predicate("macro_event_within_min", "within", 60).evaluate({"macro_event_within_min": 30})
    assert not Predicate("macro_event_within_min", "within", 60).evaluate({"macro_event_within_min": 120})


# ── Rule matching (AND) ──────────────────────────────────────────────────────
def test_rule_all_predicates_must_pass():
    snap = {"relative_volume": 1.9, "above_vwap": True, "regime": "bullish_trending"}
    rule = _rule([
        Predicate("relative_volume", "gt", 1.8),
        Predicate("above_vwap", "is_true", None),
        Predicate("regime", "contains", "trending"),
    ])
    assert rule.matches(snap)


def test_rule_fails_if_any_predicate_fails():
    snap = {"relative_volume": 1.0, "above_vwap": True}
    rule = _rule([Predicate("relative_volume", "gt", 1.8), Predicate("above_vwap", "is_true", None)])
    assert not rule.matches(snap)


def test_empty_or_disabled_rule_never_fires():
    assert not _rule([]).matches({"x": 1})
    assert not _rule([Predicate("x", "gt", 0)], enabled=False).matches({"x": 5})


# ── Mode routing ─────────────────────────────────────────────────────────────
def test_manual_is_notify_only():
    o = route_outcome(_rule([], mode="manual"), {})
    assert o.kind == "notify"
    assert o.requires_full_gate_check is False


def test_copilot_is_review_card_gated():
    o = route_outcome(_rule([], mode="copilot"), {})
    assert o.kind == "review_card"
    assert o.requires_full_gate_check is True


def test_autopilot_is_candidate_gated():
    o = route_outcome(_rule([], mode="autopilot"), {})
    assert o.kind == "candidate"
    assert o.requires_full_gate_check is True


# ── THE safety invariant ─────────────────────────────────────────────────────
def test_no_outcome_ever_creates_an_order():
    snap = {"relative_volume": 5.0, "above_vwap": True}
    for mode in ("manual", "copilot", "autopilot"):
        rule = _rule([Predicate("relative_volume", "gt", 1.0)], mode=mode)
        outcomes = evaluate_rules([rule], snap)
        assert outcomes, f"{mode} rule should have fired"
        for o in outcomes:
            d = o.to_dict()
            assert d["creates_order"] is False
            # Autopilot/copilot outcomes must be explicitly gated, never direct.
            if mode != "manual":
                assert d["requires_full_gate_check"] is True
            assert d["kind"] in ("notify", "review_card", "candidate")
