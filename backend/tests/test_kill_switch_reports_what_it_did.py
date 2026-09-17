"""
Engaging the kill switch reports what it actually flattened.

The kill switch is this app's ONLY bulk-flatten path — `engage()` cancels open
orders and sends a market order for every open position. The route used to
answer `{"engaged": true}` and throw the rest of the report away, which is a
problem in two specific ways:

  * `engage()` attempts every step even when an earlier one fails, by design
    (a broker that cannot be reached must not stop the scheduler being paused).
    So it can pause the scheduler, fail on `get_positions`, record the error,
    and still return normally. `{"engaged": true}` renders that as success.

  * `engage()` on an ALREADY-engaged switch returns at the top having
    flattened nothing at all. That is the case that matters most: an operator
    pressing it a second time because positions are still open gets the
    identical response to the press that worked.

The Risk Monitor page asserted "All orders were cancelled and positions
flattened" as static prose underneath that response. These tests pin the
counts, the already-engaged flag and the error list to what `engage()`
reported, because those three are what make the claim checkable.

No TestClient here: httpx is not installed in this environment. The route is
an ordinary coroutine and production calls this exact function, so it is
called directly rather than through a transport that would not prove more.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.routes import trade_desk as td
from app.api.routes.trade_desk import KillSwitchRequest, set_kill_switch


@pytest.fixture(autouse=True)
def _reset_local_flag():
    """The module-level Event is process-wide; leaking it poisons neighbours."""
    was_set = td._kill_switch.is_set()
    td._kill_switch.clear()
    yield
    (td._kill_switch.set() if was_set else td._kill_switch.clear())


def _engage_returning(result: dict) -> AsyncMock:
    return AsyncMock(return_value=result)


@pytest.mark.asyncio
async def test_a_successful_engage_reports_the_counts():
    engage = _engage_returning({
        "positions_flattened": 3,
        "orders_cancelled": 2,
        "errors": [],
    })
    with patch.object(td.kill_switch_service, "engage", engage):
        out = await set_kill_switch(KillSwitchRequest(engaged=True))

    assert out["engaged"] is True
    assert out["positions_flattened"] == 3
    assert out["orders_cancelled"] == 2
    assert out["errors"] == []
    assert out["already_engaged"] is False


@pytest.mark.asyncio
async def test_a_second_press_says_it_flattened_nothing():
    """The dangerous case: identical to a working press, before this change."""
    engage = _engage_returning({"status": "already_engaged", "reason": "manual"})
    with patch.object(td.kill_switch_service, "engage", engage):
        out = await set_kill_switch(KillSwitchRequest(engaged=True))

    assert out["already_engaged"] is True
    # Not "unknown" — engage() returned before flattening, so zero is the
    # truthful count, and the flag above is what tells the operator why.
    assert out["positions_flattened"] == 0
    assert out["orders_cancelled"] == 0


@pytest.mark.asyncio
async def test_a_broker_failure_reaches_the_caller():
    """Scheduler paused, broker unreachable, positions still open."""
    engage = _engage_returning({
        "positions_flattened": 0,
        "orders_cancelled": 0,
        "errors": ["get_positions: connection refused"],
    })
    with patch.object(td.kill_switch_service, "engage", engage):
        out = await set_kill_switch(KillSwitchRequest(engaged=True))

    # The switch IS engaged — that part worked, and saying otherwise would be
    # its own lie. The errors are what stop it reading as a completed flatten.
    assert out["engaged"] is True
    assert out["positions_flattened"] == 0
    assert out["errors"] == ["get_positions: connection refused"]


@pytest.mark.asyncio
async def test_a_partial_flatten_is_not_rounded_up_to_success():
    engage = _engage_returning({
        "positions_flattened": 2,
        "orders_cancelled": 1,
        "errors": ["flatten_TSLA: no market data permissions"],
    })
    with patch.object(td.kill_switch_service, "engage", engage):
        out = await set_kill_switch(KillSwitchRequest(engaged=True))

    assert out["positions_flattened"] == 2
    assert len(out["errors"]) == 1


@pytest.mark.asyncio
async def test_engage_still_sets_the_local_mirror():
    """The report is additive — it must not have displaced the actual effect."""
    engage = _engage_returning({"positions_flattened": 1, "orders_cancelled": 0, "errors": []})
    with patch.object(td.kill_switch_service, "engage", engage):
        await set_kill_switch(KillSwitchRequest(engaged=True))

    assert td._kill_switch.is_set()
    engage.assert_awaited_once()
