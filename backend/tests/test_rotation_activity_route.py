"""Tests for the GET /api/portfolio/rotation-activity route."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _event(id_, ticker, payload, created_at=datetime(2026, 8, 20, tzinfo=timezone.utc)):
    return NS(id=id_, ticker=ticker, created_at=created_at, payload=payload)


def _events_session(rows):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value = MagicMock(all=lambda: rows)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_zero_events_returns_empty_shape():
    from app.api.routes import portfolio as pmod

    with patch("app.core.database.AsyncSessionLocal", return_value=_events_session([])):
        out = await pmod.portfolio_rotation_activity()

    assert out["status"] == "no_rotations_yet"
    assert out["events"] == []


@pytest.mark.asyncio
async def test_normal_case_maps_fields_correctly():
    from app.api.routes import portfolio as pmod

    rows = [
        _event("e1", "AAPL", {
            "closed_by": "position_rotation", "status": "filled",
            "quality_score": 30.0, "in_flagged_cluster": True,
            "confidence": 0.7, "unrealized_pnl_at_decision": -50.0,
        }),
    ]
    with patch("app.core.database.AsyncSessionLocal", return_value=_events_session(rows)):
        out = await pmod.portfolio_rotation_activity()

    assert out["status"] == "ok"
    assert len(out["events"]) == 1
    ev = out["events"][0]
    assert ev["ticker"] == "AAPL"
    assert ev["asset_type"] == "equity"
    assert ev["status"] == "filled"
    assert ev["quality_score"] == 30.0
    assert ev["in_flagged_cluster"] is True
    assert ev["confidence"] == 0.7
    assert ev["unrealized_pnl_at_decision"] == -50.0
    assert ev["created_at"] is not None


@pytest.mark.asyncio
async def test_asset_type_defaults_to_equity_when_absent_from_payload():
    """close_equity_trade()'s receipt never carries an asset_type key —
    only close_options_trade()'s does. Confirm the missing-key case reads
    as equity, not None/crashing."""
    from app.api.routes import portfolio as pmod

    rows = [_event("e1", "MSFT", {"closed_by": "position_rotation", "status": "filled"})]
    with patch("app.core.database.AsyncSessionLocal", return_value=_events_session(rows)):
        out = await pmod.portfolio_rotation_activity()

    assert out["events"][0]["asset_type"] == "equity"


@pytest.mark.asyncio
async def test_options_asset_type_preserved_when_present():
    from app.api.routes import portfolio as pmod

    rows = [_event("e1", "SPY", {"closed_by": "position_rotation", "asset_type": "options", "status": "filled"})]
    with patch("app.core.database.AsyncSessionLocal", return_value=_events_session(rows)):
        out = await pmod.portfolio_rotation_activity()

    assert out["events"][0]["asset_type"] == "options"


@pytest.mark.asyncio
async def test_query_filters_on_position_rotation_closed_by():
    """The mock doesn't apply real JSONB WHERE filtering (it returns
    whatever rows it's given regardless of the query), so correctness of
    the payload->>'closed_by'=='position_rotation' filter has to be
    asserted against the compiled statement itself."""
    from app.api.routes import portfolio as pmod

    rows = [_event("e1", "AAPL", {"closed_by": "position_rotation", "status": "filled"})]
    session = _events_session(rows)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        out = await pmod.portfolio_rotation_activity()

    assert out["status"] == "ok"
    compiled = session.execute.await_args.args[0].compile(
        compile_kwargs={"literal_binds": True},
    )
    compiled_str = str(compiled)
    assert "position_rotation" in compiled_str
    assert "manual" not in compiled_str
    assert "closed_by" in compiled_str


@pytest.mark.asyncio
async def test_db_failure_returns_graceful_error():
    from app.api.routes import portfolio as pmod

    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        out = await pmod.portfolio_rotation_activity()

    assert out["status"] == "error"
    assert "db down" in out["error"]
