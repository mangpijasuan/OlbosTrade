"""
Provider abstraction for the Intelligence Hub.

Every data item returned by any provider is wrapped in a DataEnvelope carrying
its source, timestamp, freshness, confidence, and quality status. This is the
contract the UI relies on to never present delayed/free public data as
real-time institutional intelligence.

Providers are intentionally thin and swappable — premium sources (Benzinga,
Polygon, Databento, …) can be added later by implementing the same base classes
without touching business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Generic, TypeVar


class QualityStatus(str, Enum):
    OK = "ok"                # complete, within freshness budget
    STALE = "stale"          # older than the freshness budget
    PARTIAL = "partial"      # some fields missing
    UNAVAILABLE = "unavailable"  # provider down / not configured


T = TypeVar("T")


@dataclass
class DataEnvelope(Generic[T]):
    """Wraps any intel payload with provenance and quality metadata."""

    payload: T
    source: str                       # e.g. "SEC EDGAR", "yfinance", "FRED"
    as_of: datetime                   # when the data was produced/observed
    fetched_at: datetime              # when we retrieved it
    confidence: float                 # 0–1, provider-assigned
    status: QualityStatus = QualityStatus.OK
    is_delayed: bool = True           # free public data is delayed by default
    limitations: list[str] = field(default_factory=list)

    @property
    def freshness_seconds(self) -> float:
        return max(0.0, (self.fetched_at - self.as_of).total_seconds())

    def to_dict(self) -> dict:
        return {
            "payload": self.payload,
            "source": self.source,
            "as_of": self.as_of.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "freshness_seconds": round(self.freshness_seconds, 1),
            "confidence": round(self.confidence, 3),
            "status": self.status.value,
            "is_delayed": self.is_delayed,
            "limitations": self.limitations,
        }


def make_envelope(
    payload: T,
    *,
    source: str,
    as_of: datetime | None = None,
    confidence: float = 0.7,
    status: QualityStatus = QualityStatus.OK,
    is_delayed: bool = True,
    limitations: list[str] | None = None,
) -> DataEnvelope[T]:
    """Convenience constructor that stamps fetched_at = now (UTC)."""
    now = datetime.now(timezone.utc)
    return DataEnvelope(
        payload=payload,
        source=source,
        as_of=as_of or now,
        fetched_at=now,
        confidence=confidence,
        status=status,
        is_delayed=is_delayed,
        limitations=limitations or [],
    )


@dataclass
class ProviderHealth:
    name: str
    available: bool
    detail: str = ""


class IntelProvider(ABC):
    """Base for all intel providers. Subclasses declare a stable name and a
    health check so the registry can report degradation to the UI."""

    #: Stable provider identifier surfaced in DataEnvelope.source.
    name: str = "base"

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Cheap liveness/configuration check. Must never raise."""
        raise NotImplementedError


class NewsProvider(IntelProvider):
    @abstractmethod
    def fetch_news(self, symbol: str, limit: int = 20) -> list[DataEnvelope[dict]]:
        """Return recent news items for a symbol, each enveloped."""
        raise NotImplementedError


class FilingProvider(IntelProvider):
    @abstractmethod
    def fetch_filings(self, symbol: str, limit: int = 20) -> list[DataEnvelope[dict]]:
        """Return recent filings (10-K/Q, 8-K, Form 4, …) for a symbol."""
        raise NotImplementedError


class MacroProvider(IntelProvider):
    @abstractmethod
    def fetch_series(self, series_id: str) -> DataEnvelope[dict]:
        """Return the latest observation for a macro series (e.g. CPI)."""
        raise NotImplementedError
