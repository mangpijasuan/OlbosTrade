"""Tests for the /api/signal-research routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.routes import signal_research


@pytest.mark.asyncio
async def test_get_outcomes_empty_store():
    with patch("app.api.routes.signal_research._load_outcomes", return_value=[]):
        result = await signal_research.get_signal_outcomes(regime=None)
    assert result["total"] == 0
    assert "message" in result


@pytest.mark.asyncio
async def test_get_outcomes_computes_stats_from_loaded_rows():
    rows = [
        {"ticker": "AAPL", "status": "target_hit", "confidence": 0.75, "days_to_resolve": 4},
        {"ticker": "MSFT", "status": "stop_hit", "confidence": 0.68, "days_to_resolve": 2},
    ]
    with patch("app.api.routes.signal_research._load_outcomes", return_value=rows):
        result = await signal_research.get_signal_outcomes(regime=None)
    assert result["total"] == 2
    assert result["target_hit"] == 1
    assert result["stop_hit"] == 1


@pytest.mark.asyncio
async def test_get_outcomes_regime_filter_scopes_before_stats():
    rows = [
        {"ticker": "AAPL", "status": "target_hit", "confidence": 0.75,
         "days_to_resolve": 4, "regime": "low_vol_trending"},
        {"ticker": "MSFT", "status": "stop_hit", "confidence": 0.68,
         "days_to_resolve": 2, "regime": "high_vol"},
    ]
    with patch("app.api.routes.signal_research._load_outcomes", return_value=rows):
        result = await signal_research.get_signal_outcomes(regime="low_vol_trending")
    assert result["total"] == 1
    assert result["target_hit"] == 1
    assert result["stop_hit"] == 0


@pytest.mark.asyncio
async def test_get_outcomes_includes_by_regime_when_unfiltered():
    rows = [
        {"ticker": "AAPL", "status": "target_hit", "confidence": 0.75,
         "days_to_resolve": 4, "regime": "low_vol_trending"},
        {"ticker": "MSFT", "status": "stop_hit", "confidence": 0.68,
         "days_to_resolve": 2, "regime": "high_vol"},
    ]
    with patch("app.api.routes.signal_research._load_outcomes", return_value=rows):
        result = await signal_research.get_signal_outcomes(regime=None)
    assert set(result["by_regime"].keys()) == {"low_vol_trending", "high_vol"}


@pytest.mark.asyncio
async def test_get_outcomes_raw_filters_by_status():
    rows = [
        {"ticker": "AAPL", "status": "target_hit", "generated_at": "2026-01-02T00:00:00+00:00"},
        {"ticker": "MSFT", "status": "pending", "generated_at": "2026-01-03T00:00:00+00:00"},
    ]
    with patch("app.api.routes.signal_research._load_outcomes", return_value=rows):
        result = await signal_research.get_signal_outcomes_raw(limit=200, status="pending")
    assert result["total"] == 1
    assert result["outcomes"][0]["ticker"] == "MSFT"


@pytest.mark.asyncio
async def test_get_outcomes_raw_sorts_newest_first():
    rows = [
        {"ticker": "OLD", "status": "pending", "generated_at": "2026-01-01T00:00:00+00:00"},
        {"ticker": "NEW", "status": "pending", "generated_at": "2026-01-05T00:00:00+00:00"},
    ]
    with patch("app.api.routes.signal_research._load_outcomes", return_value=rows):
        result = await signal_research.get_signal_outcomes_raw(limit=200, status=None)
    assert result["outcomes"][0]["ticker"] == "NEW"


@pytest.mark.asyncio
async def test_get_outcomes_raw_respects_limit():
    rows = [
        {"ticker": f"T{i}", "status": "pending", "generated_at": f"2026-01-{i:02d}T00:00:00+00:00"}
        for i in range(1, 10)
    ]
    with patch("app.api.routes.signal_research._load_outcomes", return_value=rows):
        result = await signal_research.get_signal_outcomes_raw(limit=3, status=None)
    assert len(result["outcomes"]) == 3
    assert result["total"] == 9
