"""Tests for the assignment-risk calculator."""

from app.services.assignment_risk_calc import AssignmentInputs, assess_assignment_risk


def test_deep_otm_low_delta_is_low():
    flag = assess_assignment_risk(
        AssignmentInputs(stock_price=61.40, put_strike=58.0, delta=0.20, dte=30)
    )
    assert flag.level == "low"


def test_itm_strike_is_high():
    flag = assess_assignment_risk(
        AssignmentInputs(stock_price=57.0, put_strike=58.0, delta=0.55, dte=30)
    )
    assert flag.level == "high"


def test_high_delta_is_high():
    flag = assess_assignment_risk(
        AssignmentInputs(stock_price=61.0, put_strike=58.0, delta=0.40, dte=30)
    )
    assert flag.level == "high"


def test_thin_cushion_is_high():
    flag = assess_assignment_risk(
        AssignmentInputs(stock_price=59.0, put_strike=58.0, delta=0.22, dte=30)
    )
    assert flag.level == "high"  # < 2% OTM


def test_mid_delta_is_moderate():
    flag = assess_assignment_risk(
        AssignmentInputs(stock_price=61.0, put_strike=58.0, delta=0.28, dte=30)
    )
    assert flag.level == "moderate"


def test_label_and_detail_present():
    flag = assess_assignment_risk(
        AssignmentInputs(stock_price=61.40, put_strike=58.0, delta=0.20, dte=30)
    )
    assert flag.label and flag.detail
