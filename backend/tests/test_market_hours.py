"""
Market-hours gating tests.

  - is_market_open boundaries (open/close edges, weekend, holiday, pre/after).
  - _execute_signal blocks order submission when the market is closed, regardless
    of execution path.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.utils.market_hours import is_market_open, market_status

ET = ZoneInfo("America/New_York")


@pytest.mark.parametrize("dt,expected,reason", [
    (datetime(2026, 6, 24, 11, 0, tzinfo=ET),  True,  "open"),        # Wed midday
    (datetime(2026, 6, 24, 9, 30, tzinfo=ET),  True,  "open"),        # exactly open
    (datetime(2026, 6, 24, 15, 59, tzinfo=ET), True,  "open"),        # just before close
    (datetime(2026, 6, 24, 16, 0, tzinfo=ET),  False, "after_hours"), # exactly close
    (datetime(2026, 6, 24, 9, 0, tzinfo=ET),   False, "pre_market"),
    (datetime(2026, 6, 27, 11, 0, tzinfo=ET),  False, "weekend"),     # Saturday
    (datetime(2026, 7, 3, 11, 0, tzinfo=ET),   False, "holiday"),     # Independence Day (obs)
])
def test_is_market_open_boundaries(dt, expected, reason):
    assert is_market_open(dt) is expected
    assert market_status(dt)["reason"] == reason


@pytest.mark.asyncio
async def test_execute_signal_blocked_when_market_closed():
    """No order is submitted outside RTH; result is blocked with market_closed."""
    from app.api.routes import trade_desk
    from app.api.routes.trade_desk import _execute_signal

    signal = {
        "id": "sig-mh", "ticker": "AAPL", "action": "BUY", "asset_type": "equity",
        "trade_plan": {"shares": 10, "entry_price": 150.0},
    }
    # Ensure kill switch is off so we're testing the market gate specifically.
    trade_desk._kill_switch.clear()
    with patch("app.utils.market_hours.is_market_open", return_value=False):
        result = await _execute_signal(signal, approved_by="autopilot")

    assert result["result"] == "blocked"
    assert "market_closed" in result["reason"]
