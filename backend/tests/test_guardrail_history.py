"""Tests for real guardrail event persistence + GET /api/guardrails/history.

GET /api/guardrails/history used to unconditionally return {"events": []} —
these tests cover the fix: real events persisted on state transition
(_maybe_log_guardrail_event) and read back by the history route.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.guardrails import GuardrailStatus, PortfolioState


@pytest.fixture(autouse=True)
def _reset_signature_cache():
    import app.main as main_mod
    main_mod._last_guardrail_signature = None
    yield
    main_mod._last_guardrail_signature = None


def _status(**overrides) -> GuardrailStatus:
    base = dict(
        trading_allowed=True, trading_mode="normal", reason=None,
        cooling_off_until=None, suspended_until=None,
        daily_loss_pct=0.0, weekly_loss_pct=0.0, monthly_loss_pct=0.0,
        consecutive_losses=0, trades_today=0, capital_pct_remaining=1.0,
        flags=[],
    )
    base.update(overrides)
    return GuardrailStatus(**base)


def _portfolio(**overrides) -> PortfolioState:
    base = dict(
        current_value=100_000.0, starting_capital=100_000.0,
        daily_pnl=Decimal("0"), weekly_pnl=Decimal("0"), monthly_pnl=Decimal("0"),
        consecutive_losses=0, trades_today=0,
    )
    base.update(overrides)
    return PortfolioState(**base)


def _session_for_seed(last_row):
    """Session whose first .execute() (the seed SELECT) returns last_row."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(first=lambda: last_row)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


# ── _maybe_log_guardrail_event ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_call_seeds_from_db_and_does_not_insert_when_unchanged():
    """A fresh restart with the DB's last event matching the current live
    signature must NOT re-log a duplicate 'transition'."""
    import app.main as main_mod

    last_row = NS(event_type="normal")
    session = _session_for_seed(last_row)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await main_mod._maybe_log_guardrail_event(_status(), _portfolio())

    session.add.assert_not_called()
    assert main_mod._last_guardrail_signature == ("normal", None)


@pytest.mark.asyncio
async def test_first_call_seeds_suspended_state_correctly():
    """The DB stores only event_type (e.g. 'daily_loss_limit'), not
    trading_mode — seeding must reconstruct the full (trading_mode, flag)
    signature, not compare event_type against trading_mode directly."""
    import app.main as main_mod

    last_row = NS(event_type="daily_loss_limit")
    session = _session_for_seed(last_row)
    status = _status(trading_mode="suspended", flags=["daily_loss_limit"],
                      daily_loss_pct=-0.023, reason="Daily loss limit hit")
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await main_mod._maybe_log_guardrail_event(status, _portfolio())

    # Signature matches the seeded state — no new row.
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_first_call_ignores_kill_switch_rows_when_seeding():
    """kill_switch/kill_switch_reset aren't part of check_all()'s flag
    vocabulary — seeding must not mistake the most recent kill-switch row
    for guardrail state and must still detect a real transition."""
    import app.main as main_mod

    session = _session_for_seed(None)  # simulates the notin_() filter excluding it
    status = _status(trading_mode="capital_preservation", flags=["capital_preservation_mode"],
                      capital_pct_remaining=0.8, reason="Capital preservation active")
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await main_mod._maybe_log_guardrail_event(status, _portfolio())

    session.add.assert_called_once()
    inserted = session.add.call_args.args[0]
    assert inserted.event_type == "capital_preservation_mode"


@pytest.mark.asyncio
async def test_same_signature_twice_inserts_only_once():
    import app.main as main_mod

    session = _session_for_seed(None)
    status = _status(trading_mode="suspended", flags=["daily_loss_limit"],
                      daily_loss_pct=-0.025, reason="Daily loss limit hit")
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await main_mod._maybe_log_guardrail_event(status, _portfolio())
        await main_mod._maybe_log_guardrail_event(status, _portfolio())

    assert session.add.call_count == 1


@pytest.mark.asyncio
async def test_signature_change_inserts_with_correct_rule_specific_values():
    """The trigger/limit pair must match the rule that actually fired —
    not a single field (e.g. capital_pct_remaining) reused for every
    event type regardless of which rule triggered it."""
    import app.main as main_mod

    session = _session_for_seed(None)
    status = _status(
        trading_mode="suspended", flags=["weekly_loss_limit"],
        weekly_loss_pct=-0.06, reason="Weekly loss limit hit",
        suspended_until=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await main_mod._maybe_log_guardrail_event(status, _portfolio(current_value=94_000.0))

    inserted = session.add.call_args.args[0]
    assert inserted.event_type == "weekly_loss_limit"
    assert float(inserted.trigger_value) == -0.06
    assert float(inserted.limit_value) == -main_mod._guardrail_engine.max_weekly_loss_pct
    assert inserted.portfolio_value == Decimal("94000.0")
    assert inserted.notes == "Weekly loss limit hit"


@pytest.mark.asyncio
async def test_recovery_to_normal_is_logged_as_its_own_event():
    """History must read as a timeline (entries AND exits), not a
    one-way ratchet that only ever logs entering a restricted state."""
    import app.main as main_mod

    session = _session_for_seed(None)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await main_mod._maybe_log_guardrail_event(
            _status(trading_mode="suspended", flags=["daily_loss_limit"]), _portfolio())
        await main_mod._maybe_log_guardrail_event(_status(), _portfolio())  # back to normal

    assert session.add.call_count == 2
    assert session.add.call_args_list[1].args[0].event_type == "normal"


@pytest.mark.asyncio
async def test_persistence_failure_never_raises():
    import app.main as main_mod

    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        await main_mod._maybe_log_guardrail_event(_status(), _portfolio())  # must not raise


# ── GET /api/guardrails/history ─────────────────────────────────────────────

def _history_session(rows):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: rows)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_guardrail_history_route_empty_store():
    import app.main as main_mod

    with patch("app.core.database.AsyncSessionLocal", return_value=_history_session([])):
        result = await main_mod.guardrail_history()
    assert result == {"events": []}


@pytest.mark.asyncio
async def test_guardrail_history_route_maps_real_rows():
    import app.main as main_mod

    row = NS(
        id="11111111-1111-1111-1111-111111111111",
        timestamp=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
        event_type="daily_loss_limit",
        trigger_value=Decimal("-0.023"),
        limit_value=Decimal("-0.02"),
        trading_suspended_until=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        portfolio_value=Decimal("97700.0"),
        notes="Daily loss limit hit: -2.30% (limit: -2.00%). Trading suspended for 24h.",
    )
    with patch("app.core.database.AsyncSessionLocal", return_value=_history_session([row])):
        result = await main_mod.guardrail_history()

    event = result["events"][0]
    assert event["event_type"] == "daily_loss_limit"
    assert event["trigger_value"] == -0.023
    assert event["limit_value"] == -0.02
    assert event["portfolio_value"] == 97700.0
    assert event["timestamp"] == "2026-08-16T12:00:00+00:00"
    assert event["notes"].startswith("Daily loss limit hit")


@pytest.mark.asyncio
async def test_guardrail_history_route_db_error_returns_empty_not_500():
    import app.main as main_mod

    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        result = await main_mod.guardrail_history()
    assert result == {"events": []}
