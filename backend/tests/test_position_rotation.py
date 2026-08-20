"""Unit tests for position rotation selection + config wiring."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.position_rotation import (
    RotationCandidate,
    select_rotation_targets,
    rotate_for_new_equity_entry,
)


def _c(
    tid: str,
    underlying: str,
    pnl: float,
    conf: Optional[float],
    *,
    days_ago: int = 0,
    spread: str = "equity_long",
) -> RotationCandidate:
    entry = datetime(2026, 8, 20, tzinfo=timezone.utc)
    if days_ago:
        from datetime import timedelta
        entry = entry - timedelta(days=days_ago)
    return RotationCandidate(
        trade_id=tid,
        underlying=underlying,
        unrealized_pnl=pnl,
        confidence=conf,
        entry_date=entry,
        spread_type=spread,
    )


def test_selects_highest_pnl_then_lowest_confidence():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=100, conf=0.9),
            _c("2", "MSFT", pnl=50, conf=0.2),
            _c("3", "NVDA", pnl=80, conf=0.5),
            _c("4", "GOOG", pnl=10, conf=0.1),
            _c("5", "META", pnl=5, conf=0.8),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert [p.trade_id for p in picks] == ["1", "4"]  # best P&L, then lowest conf


def test_excludes_incoming_underlying():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=999, conf=0.9),
            _c("2", "MSFT", pnl=50, conf=0.2),
            _c("3", "NVDA", pnl=40, conf=0.1),
        ],
        incoming_ticker="AAPL",
        count=2,
    )
    assert all(p.underlying != "AAPL" for p in picks)
    assert [p.trade_id for p in picks] == ["2", "3"]


def test_returns_empty_when_not_enough_eligible():
    picks = select_rotation_targets(
        [_c("1", "AAPL", pnl=10, conf=0.5), _c("2", "MSFT", pnl=5, conf=0.4)],
        incoming_ticker="AAPL",
        count=2,
    )
    assert picks == []  # only one eligible after excluding AAPL


def test_skips_options_spread_types():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=100, conf=0.9, spread="bull_put_spread"),
            _c("2", "MSFT", pnl=50, conf=0.2),
            _c("3", "NVDA", pnl=40, conf=0.1),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert [p.trade_id for p in picks] == ["2", "3"]


def test_missing_confidence_falls_back_to_oldest():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=100, conf=None, days_ago=1),
            _c("2", "MSFT", pnl=10, conf=None, days_ago=10),
            _c("3", "NVDA", pnl=5, conf=None, days_ago=5),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    # First: highest P&L (AAPL). Second: oldest among remaining (MSFT).
    assert [p.trade_id for p in picks] == ["1", "2"]


@pytest.mark.asyncio
async def test_rotate_respects_flag_off(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "position_rotation_on_max", False)
    out = await rotate_for_new_equity_entry(
        incoming_ticker="TSLA", broker=MagicMock(),
    )
    assert out == []


@pytest.mark.asyncio
async def test_rotate_closes_selected_targets(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "position_rotation_on_max", True)
    monkeypatch.setattr(cfg.settings, "position_rotation_closes", 2)

    trades = [
        SimpleNamespace(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1",
            underlying="AAPL", spread_type="equity_long",
            quantity=10, credit_received=100, signal_score=0.9,
            entry_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2",
            underlying="MSFT", spread_type="equity_long",
            quantity=10, credit_received=100, signal_score=0.2,
            entry_date=datetime(2026, 8, 2, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3",
            underlying="NVDA", spread_type="equity_long",
            quantity=10, credit_received=100, signal_score=0.5,
            entry_date=datetime(2026, 8, 3, tzinfo=timezone.utc),
        ),
    ]

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: trades)),
    ))

    async def fake_mid(_broker, ticker):
        return {"AAPL": 110.0, "MSFT": 101.0, "NVDA": 105.0}[ticker]

    closed: list[str] = []

    async def fake_close(trade, **kwargs):
        closed.append(trade.underlying)
        return {"trade_id": str(trade.id), "ticker": trade.underlying, "status": "filled"}

    with patch("app.core.database.AsyncSessionLocal", return_value=session), \
         patch("app.services.position_rotation._mid_price", side_effect=fake_mid), \
         patch("app.services.position_rotation.close_equity_trade", side_effect=fake_close):
        out = await rotate_for_new_equity_entry(
            incoming_ticker="TSLA", broker=MagicMock(),
        )

    assert closed == ["AAPL", "MSFT"]  # best P&L then lowest conf
    assert len(out) == 2
