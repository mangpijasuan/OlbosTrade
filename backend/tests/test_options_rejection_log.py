"""Tests for options rejection persistence — the diagnostic behind "why nothing fires"."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.options_rejection_log import record_rejection

STAMP = datetime(2026, 9, 11, 14, 30, tzinfo=timezone.utc)


def _session(existing=None):
    """Mocked session; `existing` is the row the day's upsert lookup finds."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    begin = AsyncMock()
    begin.__aenter__ = AsyncMock(return_value=session)
    begin.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin)
    session.add = MagicMock()
    lookup = MagicMock()
    lookup.scalar_one_or_none = MagicMock(return_value=existing)
    session.execute = AsyncMock(return_value=lookup)
    return session


@pytest.mark.asyncio
async def test_first_rejection_of_the_day_inserts_a_row():
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        result = await record_rejection(
            ticker="AAPL", reason="IV rank too low", strategy="bull_put_spread",
            regime="low_vol_trending", now=STAMP,
        )

    assert result is not None
    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert row.ticker == "AAPL"
    assert row.reason == "IV rank too low"
    assert row.strategy == "bull_put_spread"
    assert row.regime == "low_vol_trending"
    assert row.occurrences == 1
    assert row.first_seen_at == STAMP and row.last_seen_at == STAMP


@pytest.mark.asyncio
async def test_repeat_increments_instead_of_inserting():
    """~13 scans a day would otherwise rebuild signal_outcomes' duplication."""
    existing = SimpleNamespace(
        id="row-1", occurrences=4, last_seen_at=STAMP, evidence=None,
    )
    later = STAMP.replace(hour=15)
    session = _session(existing=existing)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        result = await record_rejection(
            ticker="AAPL", reason="IV rank too low", strategy="bull_put_spread", now=later,
        )

    session.add.assert_not_called()
    assert result == "row-1"
    assert existing.occurrences == 5
    assert existing.last_seen_at == later


@pytest.mark.asyncio
async def test_repeat_backfills_evidence_only_when_missing():
    """Later repeats usually carry no SHAP evidence; the first one that does wins."""
    existing = SimpleNamespace(id="r", occurrences=1, last_seen_at=STAMP, evidence=None)
    session = _session(existing=existing)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await record_rejection(ticker="AAPL", reason="score below threshold",
                               evidence={"top_negative_factors": ["iv_rank"]}, now=STAMP)
    assert existing.evidence == {"top_negative_factors": ["iv_rank"]}

    # A second evidence payload must not overwrite the one already recorded.
    session2 = _session(existing=existing)
    with patch("app.core.database.AsyncSessionLocal", return_value=session2):
        await record_rejection(ticker="AAPL", reason="score below threshold",
                               evidence={"top_negative_factors": ["something_else"]}, now=STAMP)
    assert existing.evidence == {"top_negative_factors": ["iv_rank"]}


@pytest.mark.asyncio
async def test_null_strategy_is_matched_with_is_not_equals():
    """
    A pre-strategy rejection ("insufficient price history") has strategy=None.
    SQL `= NULL` never matches, so the lookup must use IS NULL or every scan
    would insert a new row and the counter would never increment.
    """
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await record_rejection(ticker="AAPL", reason="insufficient price history", now=STAMP)

    stmt = str(session.execute.call_args.args[0])
    assert "IS NULL" in stmt.upper()


@pytest.mark.asyncio
async def test_long_reason_is_truncated_not_dropped():
    """Reasons are built inline and can be long; a clipped one still groups."""
    session = _session()
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await record_rejection(ticker="AAPL", reason="x" * 500, now=STAMP)

    assert len(session.add.call_args.args[0].reason) == 200


@pytest.mark.asyncio
async def test_naive_timestamp_treated_as_utc():
    session = _session()
    naive = datetime(2026, 9, 11, 14, 30)
    with patch("app.core.database.AsyncSessionLocal", return_value=session):
        await record_rejection(ticker="AAPL", reason="r", now=naive)

    assert session.add.call_args.args[0].first_seen_at.tzinfo is not None


@pytest.mark.asyncio
async def test_db_failure_returns_none_and_does_not_raise():
    """A diagnostic write must never break the scan it is diagnosing."""
    with patch("app.core.database.AsyncSessionLocal", side_effect=Exception("db down")):
        result = await record_rejection(ticker="AAPL", reason="r", now=STAMP)
    assert result is None
