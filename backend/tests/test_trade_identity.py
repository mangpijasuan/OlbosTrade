"""Unit tests for (underlying, asset_class) position identity helpers."""

from types import SimpleNamespace

from app.services.trade_identity import (
    asset_class_from_signal,
    asset_class_from_trade,
    position_identity_key,
)


def test_asset_class_from_trade_equity():
    assert asset_class_from_trade(SimpleNamespace(spread_type="equity_long", strategy="x")) == "equity"
    assert asset_class_from_trade(SimpleNamespace(spread_type=None, strategy="equity")) == "equity"


def test_asset_class_from_trade_options():
    assert asset_class_from_trade(
        SimpleNamespace(spread_type="bull_put_spread", strategy="bull_put_spread")
    ) == "options"


def test_asset_class_from_signal():
    assert asset_class_from_signal({"asset_type": "equity"}) == "equity"
    assert asset_class_from_signal({"asset_type": "options"}) == "options"
    assert asset_class_from_signal({"strategy": "equity"}) == "equity"
    assert asset_class_from_signal({"spread": {"short_strike": 100}}) == "options"


def test_position_identity_key_normalized():
    assert position_identity_key("spy", "equity") == ("SPY", "equity")
    assert position_identity_key("SPY", "option") == ("SPY", "options")
