"""
The execution boundary for Capital Rotation.

Rotation may recommend a replacement. It may never close a position or open
one. Removing the close call from Stage 2b is necessary but not sufficient —
it stops that one path and says nothing about the next one someone adds — so
the boundary is enforced at the chokepoint too, inside the close functions,
and both barriers are proven here independently.

Context (2026-08-28): Stage 2b called rotate_for_blocked_entry(), which
ranked open positions worst-first and closed N of them to free a slot, then
re-checked the gate. Ranking by "most underwater" is the sunk-cost fallacy
mechanised — an existing loss carries no information about a position's
remaining prospects. With the flag armed and MSTR having drifted negative,
the next scan would have closed MRVL and MSTR for about -$11,384 combined.

Run with: pytest tests/test_rotation_execution_boundary.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.position_rotation import (
    ROTATION_CLOSED_BY,
    RotationApprovalRequired,
    close_equity_trade,
    close_options_trade,
)


def _trade(ticker="MRVL", qty=599, spread="equity_long"):
    return SimpleNamespace(
        id="trade-1", underlying=ticker, quantity=qty, spread_type=spread,
        credit_received=234.69, strategy="equity", signal_score=0.83,
        short_strike=None, long_strike=None, expiration=None, mae_pnl=None,
    )


def _broker():
    """A broker that would happily fill anything — so if a close reaches it,
    the test fails on the assertion, not on a mock error."""
    b = MagicMock()
    b.cancel_open_orders = AsyncMock(return_value=0)
    b.place_equity_order = AsyncMock(
        return_value=SimpleNamespace(status="filled", fill_price=217.0, order_id="X")
    )
    b.place_order = AsyncMock(
        return_value=SimpleNamespace(status="filled", fill_price=1.5, order_id="Y")
    )
    b.get_equity_positions = AsyncMock(
        return_value=[SimpleNamespace(symbol="MRVL", quantity=599)]
    )
    return b


# ── Barrier 1: the close functions refuse rotation without approval ──────────

@pytest.mark.asyncio
async def test_rotation_cannot_close_the_incumbent_equity():
    b = _broker()
    with pytest.raises(RotationApprovalRequired):
        await close_equity_trade(_trade(), broker=b, closed_by=ROTATION_CLOSED_BY)
    # The point is not merely that it raised — it is that nothing was sent.
    b.place_equity_order.assert_not_called()
    b.cancel_open_orders.assert_not_called()


@pytest.mark.asyncio
async def test_rotation_cannot_close_the_incumbent_options():
    b = _broker()
    with pytest.raises(RotationApprovalRequired):
        await close_options_trade(
            _trade(spread="put"), broker=b, closed_by=ROTATION_CLOSED_BY
        )
    b.place_order.assert_not_called()
    b.cancel_open_orders.assert_not_called()


@pytest.mark.asyncio
async def test_forgetting_the_kwarg_fails_closed():
    """close_equity_trade defaults closed_by to 'position_rotation', so a
    caller who omits it must be refused rather than silently submitting an
    unreviewed close."""
    b = _broker()
    with pytest.raises(RotationApprovalRequired):
        await close_equity_trade(_trade(), broker=b)
    b.place_equity_order.assert_not_called()


@pytest.mark.asyncio
async def test_an_empty_approval_token_is_not_an_approval():
    b = _broker()
    for token in ("", None):
        with pytest.raises(RotationApprovalRequired):
            await close_equity_trade(
                _trade(), broker=b, closed_by=ROTATION_CLOSED_BY,
                rotation_approval=token,
            )
    b.place_equity_order.assert_not_called()


@pytest.mark.asyncio
async def test_manual_close_is_unaffected_by_the_guard():
    """The guard must not break the human's own close button."""
    b = _broker()
    with patch("app.services.trade_recorder.trade_recorder.record_exit",
               new=AsyncMock()), \
         patch("app.broker.ibkr_coordinator.ibkr_coordinator.submit",
               new=AsyncMock(return_value=SimpleNamespace(
                   status="filled", fill_price=217.0, order_id="X"))):
        out = await close_equity_trade(_trade(), broker=b, closed_by="manual")
    assert out["closed_by"] == "manual"


# ── Barrier 2: Stage 2b raises a review and executes nothing ─────────────────

from app.services.guardrails import PortfolioState


def _clean():
    return PortfolioState(current_value=250_000.0, starting_capital=250_000.0,
                          daily_pnl=0.0, weekly_pnl=0.0, monthly_pnl=0.0,
                          consecutive_losses=0, trades_today=0)


def _signal(ticker="TSLA"):
    return {
        "ticker": ticker, "action": "BUY", "asset_type": "equity",
        # 0.95 clears Balanced mode's 0.90 min-confidence floor at Stage 1c;
        # a lower value is blocked before Stage 2b is ever reached.
        "confidence": 0.95, "alpha_edge_score": 74, "regime": "low_vol_trending",
        # risk_reward is what Stage 1c's EV gate reads; without it the
        # ratio is 0.0 and EV goes negative, blocking before Stage 2b.
        "trade_plan": {"shares": 10, "entry_price": 100.0, "risk_reward": 2.0,
                       "stop_price": 96.0, "target_price": 108.0},
    }


class _Gate:
    """Stands in for PortfolioGateResult — the max_positions block that used
    to trigger an automatic close."""
    def __init__(self, allowed, flags=None, reason=""):
        self.allowed, self.flags, self.reason = allowed, flags or [], reason


def _stage_2b_env(*, rotation_enabled=True, broker=None):
    """Everything upstream of Stage 2b passes, so the branch under test is the
    only thing exercised. Patch paths match the seams the existing suite uses:
    the portfolio gate is a function-local import, so it is patched at its
    source module, not on trade_desk."""
    return [
        patch("app.api.routes.trade_desk._fetch_portfolio_state",
              new=AsyncMock(return_value=_clean())),
        patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=False),
        patch("app.api.routes.trade_desk._strategy_health_for",
              new=AsyncMock(return_value=None)),
        patch("app.utils.market_hours.is_market_open", return_value=True),
        patch("app.services.execution_portfolio_gate.check_execution_portfolio",
              new=AsyncMock(return_value=_Gate(
                  False, ["max_positions"], "Max concurrent positions reached: 3/3"))),
        patch("app.core.config.settings.position_rotation_on_max", rotation_enabled),
        patch("app.broker.broker_factory.get_broker",
              return_value=broker if broker is not None else _broker()),
    ]


@pytest.mark.asyncio
async def test_stage_2b_returns_pending_approval_and_closes_nothing():
    import contextlib
    import app.api.routes.trade_desk as td
    with contextlib.ExitStack() as st:
        for p in _stage_2b_env():
            st.enter_context(p)
        log = st.enter_context(
            patch("app.api.routes.trade_desk._log_execution", new=AsyncMock()))
        close_eq = st.enter_context(
            patch("app.services.position_rotation.close_equity_trade", new=AsyncMock()))
        close_opt = st.enter_context(
            patch("app.services.position_rotation.close_options_trade", new=AsyncMock()))
        rotate = st.enter_context(
            patch("app.services.position_rotation.rotate_for_blocked_entry",
                  new=AsyncMock()))
        result = await td._execute_signal(_signal(), approved_by="autopilot")

    assert result["result"] == "skipped"
    assert result["reason"] == "rotation_pending_approval"
    # The three ways rotation could have reached the money path:
    rotate.assert_not_called()
    close_eq.assert_not_called()
    close_opt.assert_not_called()


@pytest.mark.asyncio
async def test_stage_2b_emits_a_rotation_review_intent():
    import contextlib
    import app.api.routes.trade_desk as td
    with contextlib.ExitStack() as st:
        for p in _stage_2b_env():
            st.enter_context(p)
        log = st.enter_context(
            patch("app.api.routes.trade_desk._log_execution", new=AsyncMock()))
        await td._execute_signal(_signal(), approved_by="autopilot")

    entries = [c.args[0] for c in log.await_args_list if c.args]
    review = next(e for e in entries if e.get("kind") == "ROTATION_REVIEW")
    assert review["result"] == "pending_approval"
    assert review["review"]["auto_executable"] is False
    assert review["review"]["requires_approval"] is True
    assert review["review"]["sunk_cost_excluded"] is True


@pytest.mark.asyncio
async def test_stage_2b_does_not_open_the_challenger():
    """A review is not an entry ticket. 'skipped' must mean nothing was sent
    — neither a close for the incumbent nor an entry for the challenger."""
    import contextlib
    import app.api.routes.trade_desk as td
    broker = _broker()
    with contextlib.ExitStack() as st:
        for p in _stage_2b_env(broker=broker):
            st.enter_context(p)
        st.enter_context(
            patch("app.api.routes.trade_desk._log_execution", new=AsyncMock()))
        result = await td._execute_signal(_signal(), approved_by="autopilot")

    assert result["result"] == "skipped"
    broker.place_equity_order.assert_not_called()
    broker.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_rotation_disabled_still_blocks_at_the_gate_as_before():
    """Unrelated behaviour must not shift: with rotation off, a max_positions
    block stays a plain portfolio_gate block, not a review."""
    import contextlib
    import app.api.routes.trade_desk as td
    with contextlib.ExitStack() as st:
        for p in _stage_2b_env(rotation_enabled=False):
            st.enter_context(p)
        log = st.enter_context(
            patch("app.api.routes.trade_desk._log_execution", new=AsyncMock()))
        result = await td._execute_signal(_signal(), approved_by="autopilot")

    assert result["result"] == "blocked"
    assert "portfolio_gate" in result["reason"]
    kinds = [c.args[0].get("kind") for c in log.await_args_list if c.args]
    assert "ROTATION_REVIEW" not in kinds


@pytest.mark.asyncio
async def test_gate_allowed_signal_is_not_diverted_into_a_review():
    """Stage 2b must be transparent when the portfolio gate allows the signal:
    no review, no rotation skip, execution carries on to the later stages.

    Scoped deliberately to what this change could break — whether the order
    ultimately reaches the broker depends on Stages 3-5 and a lot of unrelated
    mocking. The real regression evidence that normal execution still submits
    is the existing test_trade_desk_routes.py suite, which passes untouched.
    """
    import contextlib
    import app.api.routes.trade_desk as td
    with contextlib.ExitStack() as st:
        st.enter_context(patch("app.api.routes.trade_desk._fetch_portfolio_state",
                               new=AsyncMock(return_value=_clean())))
        st.enter_context(patch("app.api.routes.trade_desk._is_kill_switch_active",
                               return_value=False))
        st.enter_context(patch("app.api.routes.trade_desk._strategy_health_for",
                               new=AsyncMock(return_value=None)))
        st.enter_context(patch("app.utils.market_hours.is_market_open", return_value=True))
        st.enter_context(patch(
            "app.services.execution_portfolio_gate.check_execution_portfolio",
            new=AsyncMock(return_value=_Gate(True))))
        st.enter_context(patch("app.core.config.settings.position_rotation_on_max", True))
        st.enter_context(patch("app.broker.broker_factory.get_broker",
                               return_value=_broker()))
        st.enter_context(patch("app.core.database.AsyncSessionLocal",
                               return_value=_no_rows_session()))
        log = st.enter_context(patch("app.api.routes.trade_desk._log_execution",
                                     new=AsyncMock()))
        st.enter_context(patch("app.services.trade_recorder.trade_recorder.record_fill",
                               new=AsyncMock(return_value="trade-1")))
        result = await td._execute_signal(_signal(), approved_by="autopilot")

    assert result.get("reason") != "rotation_pending_approval"
    kinds = [c.args[0].get("kind") for c in log.await_args_list if c.args]
    assert "ROTATION_REVIEW" not in kinds


def _no_rows_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: [])
    result.first = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    return session


# ── Independence of the upstream risk controls ───────────────────────────────

@pytest.mark.asyncio
async def test_kill_switch_still_stops_everything_ahead_of_rotation():
    """Rotation sits at Stage 2b, downstream of the kill switch at Stage 1.
    An engaged kill switch must short-circuit before any review is built."""
    import app.api.routes.trade_desk as td
    with patch("app.api.routes.trade_desk._is_kill_switch_active", return_value=True), \
         patch("app.api.routes.trade_desk._log_execution", new=AsyncMock()) as log, \
         patch("app.services.execution_portfolio_gate.check_execution_portfolio",
               new=AsyncMock()) as gate:
        result = await td._execute_signal(_signal(), approved_by="autopilot")

    assert result["result"] == "blocked"
    gate.assert_not_called()          # never reached the portfolio gate at all
    kinds = [c.args[0].get("kind") for c in log.await_args_list if c.args]
    assert "ROTATION_REVIEW" not in kinds


@pytest.mark.asyncio
async def test_neither_execution_mode_can_bypass_the_close_guard():
    """The guard is mode-independent by construction — it lives in the close
    function, which knows nothing about execution mode. Proven for both
    rather than assumed."""
    from app.services.execution_mode import ExecutionMode, execution_mode_manager

    b = _broker()
    for mode in (ExecutionMode.AUTOPILOT, ExecutionMode.COPILOT):
        with patch.object(type(execution_mode_manager), "mode",
                          property(lambda self, m=mode: m)):
            with pytest.raises(RotationApprovalRequired):
                await close_equity_trade(
                    _trade(), broker=b, closed_by=ROTATION_CLOSED_BY,
                )
    b.place_equity_order.assert_not_called()
