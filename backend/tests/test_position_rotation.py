"""Unit tests for position rotation selection + config wiring."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import rotation_correlation_cache
from app.services.position_rotation import (
    RotationCandidate,
    close_options_trade,
    select_rotation_targets,
    rotate_for_new_equity_entry,
)


@pytest.fixture(autouse=True)
def _reset_correlation_cache():
    rotation_correlation_cache.clear()
    yield
    rotation_correlation_cache.clear()


def _c(
    tid: str,
    underlying: str,
    pnl: float,
    conf: Optional[float] = None,
    *,
    quality: Optional[float] = None,
    in_cluster: Optional[bool] = None,
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
        quality_score=quality,
        in_flagged_cluster=in_cluster,
    )


def test_never_selects_profitable_position():
    """The core Winner Protection guarantee: a profitable position with the
    weakest quality score must never be picked — the old algorithm would
    have picked it first ("bank the winner")."""
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=50, quality=1),      # winner, weakest thesis — must be protected
            _c("2", "MSFT", pnl=-10, quality=80),
            _c("3", "NVDA", pnl=-5, quality=60),
        ],
        incoming_ticker="TSLA",
        count=1,
    )
    assert "1" not in [p.trade_id for p in picks]
    assert [p.trade_id for p in picks] == ["3"]  # lowest quality among eligible


def test_insufficient_eligible_after_winner_protection_returns_empty():
    """Only winners are open — rotation must skip entirely (leave the new
    signal blocked) rather than touch a winner to hit the requested count."""
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=100),
            _c("2", "MSFT", pnl=50),
            _c("3", "NVDA", pnl=-5),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert picks == []


def test_prefers_worst_quality_score_among_eligible():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=-5, quality=90),
            _c("2", "MSFT", pnl=-10, quality=20),
            _c("3", "NVDA", pnl=-3, quality=50),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert [p.trade_id for p in picks] == ["2", "3"]  # ascending quality


def test_cluster_membership_breaks_quality_score_tie():
    """Two candidates share the same quality_score — the one in a flagged
    correlation cluster must be picked first (tiebreaker only)."""
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=-5, quality=50, in_cluster=True),
            _c("2", "MSFT", pnl=-5, quality=50, in_cluster=False),
            _c("3", "NVDA", pnl=-5, quality=90),  # clearly best quality, must survive
        ],
        incoming_ticker="TSLA",
        count=1,
    )
    assert [p.trade_id for p in picks] == ["1"]


def test_cluster_membership_never_overrides_real_quality_difference():
    """AAPL is clustered but has the *better* quality score than MSFT
    (not clustered) — quality_score must still win; the tiebreaker only
    applies within a quality tier, never across one."""
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=-5, quality=80, in_cluster=True),
            _c("2", "MSFT", pnl=-5, quality=20, in_cluster=False),
        ],
        incoming_ticker="TSLA",
        count=1,
    )
    assert [p.trade_id for p in picks] == ["2"]  # worse quality wins despite not being clustered


def test_cluster_membership_none_is_neutral_not_biased_either_way():
    """Fail-open regression: with in_flagged_cluster left at its default
    (None, i.e. cache stale/missing), ranking must fall straight through
    to confidence/entry_date exactly as before this tiebreaker existed."""
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=-5, conf=0.9),
            _c("2", "MSFT", pnl=-5, conf=0.2),
            _c("3", "NVDA", pnl=-5, conf=0.5),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert [p.trade_id for p in picks] == ["2", "3"]


def test_quality_score_missing_falls_back_to_confidence():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=-5, conf=0.9),
            _c("2", "MSFT", pnl=-5, conf=0.2),
            _c("3", "NVDA", pnl=-5, conf=0.5),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert [p.trade_id for p in picks] == ["2", "3"]  # ascending confidence


def test_quality_and_confidence_missing_falls_back_to_oldest_entry_date():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=-5, days_ago=1),
            _c("2", "MSFT", pnl=-5, days_ago=10),
            _c("3", "NVDA", pnl=-5, days_ago=5),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert [p.trade_id for p in picks] == ["2", "3"]  # oldest first


def test_excludes_incoming_underlying():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=-999, quality=1),
            _c("2", "MSFT", pnl=-50, quality=30),
            _c("3", "NVDA", pnl=-40, quality=70),
        ],
        incoming_ticker="AAPL",
        count=2,
    )
    assert all(p.underlying != "AAPL" for p in picks)
    assert [p.trade_id for p in picks] == ["2", "3"]


def test_returns_empty_when_not_enough_eligible_after_ticker_exclusion():
    picks = select_rotation_targets(
        [_c("1", "AAPL", pnl=-10), _c("2", "MSFT", pnl=-5)],
        incoming_ticker="AAPL",
        count=2,
    )
    assert picks == []  # only MSFT eligible after excluding AAPL


def test_skips_options_spread_types():
    picks = select_rotation_targets(
        [
            _c("1", "AAPL", pnl=100, quality=1, spread="bull_put_spread"),
            _c("2", "MSFT", pnl=-50, quality=30),
            _c("3", "NVDA", pnl=-40, quality=70),
        ],
        incoming_ticker="TSLA",
        count=2,
    )
    assert [p.trade_id for p in picks] == ["2", "3"]


@pytest.mark.asyncio
async def test_rotate_respects_flag_off(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "position_rotation_on_max", False)
    out = await rotate_for_new_equity_entry(
        incoming_ticker="TSLA", broker=MagicMock(),
    )
    assert out == []


@pytest.mark.asyncio
async def test_rotate_closes_selected_targets_and_protects_the_winner(monkeypatch):
    """End-to-end: MSFT is both the biggest winner AND the weakest
    confidence — the old algorithm would bank it first, then close it again
    on the confidence tiebreak. It must survive both rounds."""
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

    # MSFT is the biggest winner (+100); AAPL and NVDA are losses.
    async def fake_mid(_broker, ticker):
        return {"AAPL": 90.0, "MSFT": 110.0, "NVDA": 95.0}[ticker]

    async def fake_quality(ticker, _direction):
        return {"AAPL": 30.0, "MSFT": 10.0, "NVDA": 70.0}[ticker]

    closed: list[str] = []

    async def fake_close(trade, **kwargs):
        closed.append(trade.underlying)
        return {"trade_id": str(trade.id), "ticker": trade.underlying, "status": "filled"}

    with patch("app.core.database.AsyncSessionLocal", return_value=session), \
         patch("app.services.position_rotation._mid_price", side_effect=fake_mid), \
         patch("app.services.alpha_edge_engine.compute_equity_hold_score", side_effect=fake_quality), \
         patch("app.services.position_rotation.close_equity_trade", side_effect=fake_close):
        out = await rotate_for_new_equity_entry(
            incoming_ticker="TSLA", broker=MagicMock(),
        )

    assert "MSFT" not in closed  # the winner, even with the weakest confidence, is protected
    assert closed == ["AAPL", "NVDA"]  # ascending quality among the eligible (losing) positions
    assert len(out) == 2

    # The receipt (later persisted into ExecutionEvent.payload for the
    # rotation-performance ledger) must carry the decision-time ranking
    # signals, not just the close mechanics.
    aapl_receipt = next(r for r in out if r["ticker"] == "AAPL")
    assert aapl_receipt["quality_score"] == 30.0
    assert aapl_receipt["confidence"] == 0.9
    assert aapl_receipt["unrealized_pnl_at_decision"] == -100.0  # (90-100)*10
    assert aapl_receipt["in_flagged_cluster"] is None  # no correlation cache populated in this test


@pytest.mark.asyncio
async def test_rotate_quality_lookup_failure_falls_back_to_confidence(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "position_rotation_on_max", True)
    monkeypatch.setattr(cfg.settings, "position_rotation_closes", 1)

    trades = [
        SimpleNamespace(
            id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1",
            underlying="AAPL", spread_type="equity_long",
            quantity=10, credit_received=100, signal_score=0.9,
            entry_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2",
            underlying="MSFT", spread_type="equity_long",
            quantity=10, credit_received=100, signal_score=0.2,
            entry_date=datetime(2026, 8, 2, tzinfo=timezone.utc),
        ),
    ]

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: trades)),
    ))

    async def fake_mid(_broker, ticker):
        return {"AAPL": 90.0, "MSFT": 95.0}[ticker]  # both losses

    closed: list[str] = []

    async def fake_close(trade, **kwargs):
        closed.append(trade.underlying)
        return {"trade_id": str(trade.id), "ticker": trade.underlying, "status": "filled"}

    with patch("app.core.database.AsyncSessionLocal", return_value=session), \
         patch("app.services.position_rotation._mid_price", side_effect=fake_mid), \
         patch("app.services.alpha_edge_engine.compute_equity_hold_score",
               side_effect=RuntimeError("quality lookup failed")), \
         patch("app.services.position_rotation.close_equity_trade", side_effect=fake_close):
        out = await rotate_for_new_equity_entry(
            incoming_ticker="TSLA", broker=MagicMock(),
        )

    # Quality lookup failed for both -> falls back to lowest confidence (MSFT, 0.2).
    assert closed == ["MSFT"]


# ── close_options_trade ──────────────────────────────────────────────────

def _opt_trade(spread_type="put", short=100, long=95, qty=2, strategy="bull_put_spread"):
    return SimpleNamespace(
        id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1",
        underlying="SPY", spread_type=spread_type, strategy=strategy,
        short_strike=Decimal(str(short)), long_strike=Decimal(str(long)),
        expiration=date(2026, 9, 18), quantity=qty,
    )


@pytest.mark.asyncio
async def test_close_options_trade_success_correct_leg_actions_and_mkt():
    trade = _opt_trade()
    broker = MagicMock()
    broker.cancel_open_orders = AsyncMock(return_value=1)
    broker.place_order = AsyncMock(return_value=MagicMock(
        status="filled", order_id="ord-opt-1", fill_price=Decimal("1.50"),
    ))
    with patch("app.services.trade_recorder.trade_recorder.record_exit",
               new=AsyncMock(return_value=True)) as record_mock:
        out = await close_options_trade(trade, broker=broker, closed_by="manual")

    broker.place_order.assert_awaited_once()
    order = broker.place_order.await_args.args[0]
    assert order.order_type == "MKT"
    assert order.limit_price == Decimal("0")
    short_leg, long_leg = order.legs
    assert short_leg.strike == Decimal("100") and short_leg.action == "BUY"
    assert long_leg.strike == Decimal("95") and long_leg.action == "SELL"
    assert short_leg.option_type == "put" and long_leg.option_type == "put"
    assert short_leg.quantity == 2 and long_leg.quantity == 2

    record_mock.assert_awaited_once()
    assert record_mock.await_args.kwargs["cost_to_close"] == 1.50
    assert record_mock.await_args.kwargs["exit_reason"] == "manual"
    assert out["status"] == "filled"
    assert out["option_type"] == "put"
    assert out["cancelled_open_orders"] == 1


@pytest.mark.asyncio
async def test_close_options_trade_broker_rejection_raises_runtimeerror():
    trade = _opt_trade()
    broker = MagicMock()
    broker.cancel_open_orders = AsyncMock(return_value=0)
    broker.place_order = AsyncMock(return_value=MagicMock(
        status="rejected", order_id=None, fill_price=None,
    ))
    with pytest.raises(RuntimeError):
        await close_options_trade(trade, broker=broker)


@pytest.mark.asyncio
async def test_close_options_trade_missing_strikes_raises_valueerror():
    trade = _opt_trade()
    trade.short_strike = None
    broker = MagicMock()
    broker.place_order = AsyncMock()
    with pytest.raises(ValueError):
        await close_options_trade(trade, broker=broker)
    broker.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_options_trade_missing_expiration_raises_valueerror():
    trade = _opt_trade()
    trade.expiration = None
    broker = MagicMock()
    with pytest.raises(ValueError):
        await close_options_trade(trade, broker=broker)


@pytest.mark.asyncio
async def test_close_options_trade_non_option_spread_type_raises_valueerror():
    trade = _opt_trade(spread_type="equity_long")
    broker = MagicMock()
    with pytest.raises(ValueError):
        await close_options_trade(trade, broker=broker)


@pytest.mark.asyncio
async def test_close_options_trade_not_filled_skips_record_exit():
    trade = _opt_trade()
    broker = MagicMock()
    broker.cancel_open_orders = AsyncMock(return_value=0)
    broker.place_order = AsyncMock(return_value=MagicMock(
        status="submitted", order_id="ord-opt-2", fill_price=None,
    ))
    with patch("app.services.trade_recorder.trade_recorder.record_exit",
               new=AsyncMock(return_value=True)) as record_mock:
        out = await close_options_trade(trade, broker=broker)

    record_mock.assert_not_awaited()
    assert out["status"] == "submitted"
