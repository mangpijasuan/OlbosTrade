"""
GET /api/equity/signals' default limit — was 50, silently truncating a
single scan cycle to half the watchlist once it grew past 50 tickers
(102 as of the Nasdaq-100 switch, one entry produced per ticker per
cycle). Confirmed by the user directly: "i only see 50 tickers".
"""

from __future__ import annotations

import inspect

from app.api.routes.equity import list_equity_signals


def test_default_limit_covers_a_full_watchlist_cycle():
    default = inspect.signature(list_equity_signals).parameters["limit"].default
    assert default >= 102
