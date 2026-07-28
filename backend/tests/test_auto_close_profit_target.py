"""
Auto-close: close any open equity position once unrealized profit crosses
settings.auto_close_profit_threshold (operator ask: "close every ticker
once it's up $500"). An exit rule — reuses close_position, so it inherits
the same equity-only scope and the same cancel-bracket-then-close safety.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import app.main as m


def _position(**overrides):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "symbol": "AAPL",
        "spread_type": "equity_long",
        "unrealized_pnl": 600.0,
        "tracked": True,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_auto_close_disabled_when_threshold_zero(monkeypatch):
    monkeypatch.setattr(m.settings, "auto_close_profit_threshold", 0)
    with patch("app.api.routes.paper_trade.get_positions", new=AsyncMock()) as get_pos:
        await m._check_auto_close_profit_targets()
    get_pos.assert_not_called()


@pytest.mark.asyncio
async def test_auto_close_fires_above_threshold(monkeypatch):
    monkeypatch.setattr(m.settings, "auto_close_profit_threshold", 500.0)
    with patch("app.api.routes.paper_trade.get_positions",
               new=AsyncMock(return_value={"positions": [_position(unrealized_pnl=600.0)]})), \
         patch("app.api.routes.trade_desk.close_position",
               new=AsyncMock(return_value={"status": "filled"})) as close_mock:
        await m._check_auto_close_profit_targets()
    close_mock.assert_awaited_once()
    req = close_mock.await_args.args[0]
    assert req.trade_id == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_auto_close_skips_below_threshold(monkeypatch):
    monkeypatch.setattr(m.settings, "auto_close_profit_threshold", 500.0)
    with patch("app.api.routes.paper_trade.get_positions",
               new=AsyncMock(return_value={"positions": [_position(unrealized_pnl=200.0)]})), \
         patch("app.api.routes.trade_desk.close_position", new=AsyncMock()) as close_mock:
        await m._check_auto_close_profit_targets()
    close_mock.assert_not_called()


@pytest.mark.asyncio
async def test_auto_close_skips_options_positions(monkeypatch):
    monkeypatch.setattr(m.settings, "auto_close_profit_threshold", 500.0)
    with patch("app.api.routes.paper_trade.get_positions",
               new=AsyncMock(return_value={
                   "positions": [_position(spread_type="put", unrealized_pnl=9000.0)],
               })), \
         patch("app.api.routes.trade_desk.close_position", new=AsyncMock()) as close_mock:
        await m._check_auto_close_profit_targets()
    close_mock.assert_not_called()


@pytest.mark.asyncio
async def test_auto_close_skips_untracked_ghost_positions(monkeypatch):
    monkeypatch.setattr(m.settings, "auto_close_profit_threshold", 500.0)
    with patch("app.api.routes.paper_trade.get_positions",
               new=AsyncMock(return_value={
                   "positions": [_position(tracked=False, unrealized_pnl=9000.0)],
               })), \
         patch("app.api.routes.trade_desk.close_position", new=AsyncMock()) as close_mock:
        await m._check_auto_close_profit_targets()
    close_mock.assert_not_called()


@pytest.mark.asyncio
async def test_auto_close_one_failure_does_not_block_the_rest(monkeypatch):
    monkeypatch.setattr(m.settings, "auto_close_profit_threshold", 500.0)
    positions = [
        _position(id="aaaaaaaa-0000-0000-0000-000000000000", symbol="AAPL"),
        _position(id="bbbbbbbb-0000-0000-0000-000000000000", symbol="MSFT"),
    ]
    with patch("app.api.routes.paper_trade.get_positions",
               new=AsyncMock(return_value={"positions": positions})), \
         patch("app.api.routes.trade_desk.close_position",
               new=AsyncMock(side_effect=[RuntimeError("broker down"),
                                           {"status": "filled"}])) as close_mock:
        await m._check_auto_close_profit_targets()
    assert close_mock.await_count == 2
