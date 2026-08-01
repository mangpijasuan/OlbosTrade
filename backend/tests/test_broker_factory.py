"""Tests for get_broker()/reset_broker() — the settings.broker → concrete
client dispatch, including the new "alpaca" branch."""

from __future__ import annotations

import pytest

from app.broker import broker_factory
from app.broker.alpaca_client import AlpacaClient
from app.broker.ibkr_client import IBKRClient


@pytest.fixture(autouse=True)
def _reset():
    broker_factory.reset_broker()
    yield
    broker_factory.reset_broker()


def test_get_broker_returns_ibkr_client(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "broker", "ibkr")
    broker = broker_factory.get_broker()
    assert isinstance(broker, IBKRClient)


def test_get_broker_returns_alpaca_client(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "broker", "alpaca")
    broker = broker_factory.get_broker()
    assert isinstance(broker, AlpacaClient)


def test_get_broker_is_case_insensitive(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "broker", "ALPACA")
    broker = broker_factory.get_broker()
    assert isinstance(broker, AlpacaClient)


def test_get_broker_raises_on_unknown_name(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "broker", "robinhood")
    with pytest.raises(ValueError, match="Unknown broker"):
        broker_factory.get_broker()


def test_get_broker_returns_same_singleton_instance(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "broker", "alpaca")
    first = broker_factory.get_broker()
    second = broker_factory.get_broker()
    assert first is second


def test_reset_broker_clears_singleton(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "broker", "alpaca")
    first = broker_factory.get_broker()
    broker_factory.reset_broker()
    second = broker_factory.get_broker()
    assert first is not second
