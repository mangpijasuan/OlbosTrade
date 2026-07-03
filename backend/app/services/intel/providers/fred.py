"""
FRED macro provider (free, requires a free API key).

Fetches the latest observation for a macro series (CPI, unemployment, etc.).
FRED needs an API key; without FRED_API_KEY set, health() reports unavailable
and the data-quality score honestly reflects the missing capability rather than
pretending macro data is present.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from app.services.intel.provider_base import (
    DataEnvelope, MacroProvider, ProviderHealth, QualityStatus, make_envelope,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Friendly names for common series surfaced in the UI.
SERIES = {
    "CPIAUCSL": "CPI (all urban consumers)",
    "UNRATE": "Unemployment rate",
    "DFF": "Fed funds rate",
    "T10Y2Y": "10Y-2Y Treasury spread",
}


class FredProvider(MacroProvider):
    name = "FRED"

    def __init__(self) -> None:
        self._key = os.environ.get("FRED_API_KEY", "").strip()

    def health(self) -> ProviderHealth:
        if not self._key:
            return ProviderHealth(self.name, available=False, detail="FRED_API_KEY not set")
        return ProviderHealth(self.name, available=True, detail="free API key configured")

    def fetch_series(self, series_id: str) -> DataEnvelope[dict]:
        if not self._key:
            return make_envelope(
                {"series_id": series_id, "value": None},
                source=self.name, confidence=0.0,
                status=QualityStatus.UNAVAILABLE, is_delayed=True,
                limitations=["FRED_API_KEY not configured"],
            )
        try:
            r = httpx.get(_BASE, params={
                "series_id": series_id, "api_key": self._key, "file_type": "json",
                "sort_order": "desc", "limit": "1",
            }, timeout=6.0)
            obs = (r.json().get("observations") or [{}])[0] if r.status_code == 200 else {}
            value = obs.get("value")
            as_of = _parse_date(obs.get("date"))
            return make_envelope(
                {"series_id": series_id, "name": SERIES.get(series_id, series_id),
                 "value": value, "observation_date": obs.get("date")},
                source=self.name, as_of=as_of, confidence=0.95,
                status=QualityStatus.OK if value not in (None, ".") else QualityStatus.PARTIAL,
                is_delayed=True,
                limitations=["Macro series are released on a lag by the source agency"],
            )
        except Exception as exc:
            logger.warning("FRED fetch failed for %s: %s", series_id, exc)
            return make_envelope(
                {"series_id": series_id, "value": None},
                source=self.name, confidence=0.0,
                status=QualityStatus.UNAVAILABLE, is_delayed=True,
                limitations=["FRED request failed"],
            )


def _parse_date(s: str | None) -> datetime:
    try:
        return datetime.fromisoformat(s) if s else datetime.now(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)
