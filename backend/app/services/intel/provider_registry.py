"""
Provider registry + data-quality scoring.

Holds the set of configured providers, reports their health, and computes a
0–100 data-quality score for a symbol from which capabilities are actually
available. The score is used to REDUCE confidence where missing data materially
affects analysis (Module 10) — it never inflates it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.intel.provider_base import (
    FilingProvider,
    IntelProvider,
    MacroProvider,
    NewsProvider,
    ProviderHealth,
)

# Capabilities that contribute to the data-quality score, with weights.
# Price/volume and the free public feeds we actually have are weighted highest;
# premium-only capabilities count against completeness when absent.
_CAPABILITY_WEIGHTS: dict[str, int] = {
    "price_volume": 25,
    "earnings_calendar": 15,
    "sec_filings": 15,
    "options_chain": 15,
    "news_feed": 15,
    "macro_data": 15,
}

# Capabilities we do not have on free tiers — surfaced as "unavailable" so the UI
# never implies institutional-grade coverage.
_KNOWN_UNAVAILABLE = [
    "Full intraday options flow",
    "Dark-pool data",
    "Level II order book",
    "Premium breaking-news feed",
]


@dataclass
class DataQualityReport:
    symbol: str
    score: int                          # 0–100
    available: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    providers: list[ProviderHealth] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "available": self.available,
            "unavailable": self.unavailable,
            "providers": [
                {"name": p.name, "available": p.available, "detail": p.detail}
                for p in self.providers
            ],
        }


class ProviderRegistry:
    def __init__(self) -> None:
        self._news: list[NewsProvider] = []
        self._filings: list[FilingProvider] = []
        self._macro: list[MacroProvider] = []

    # ── Registration ─────────────────────────────────────────────────────────
    def register(self, provider: IntelProvider) -> None:
        if isinstance(provider, NewsProvider):
            self._news.append(provider)
        if isinstance(provider, FilingProvider):
            self._filings.append(provider)
        if isinstance(provider, MacroProvider):
            self._macro.append(provider)

    def all_providers(self) -> list[IntelProvider]:
        seen: dict[int, IntelProvider] = {}
        for p in [*self._news, *self._filings, *self._macro]:
            seen[id(p)] = p
        return list(seen.values())

    def health(self) -> list[ProviderHealth]:
        out: list[ProviderHealth] = []
        for p in self.all_providers():
            try:
                out.append(p.health())
            except Exception:  # providers must not break the registry
                out.append(ProviderHealth(name=getattr(p, "name", "?"), available=False, detail="health check failed"))
        return out

    # ── Data-quality score ───────────────────────────────────────────────────
    def data_quality(
        self,
        symbol: str,
        *,
        has_price_volume: bool = True,
        has_earnings: bool = True,
        has_options: bool = True,
    ) -> DataQualityReport:
        """Compute a completeness score from live capabilities.

        Baseline capabilities (price/volume, earnings, options) come from the
        existing market-data stack; news/filings/macro come from registered
        providers' health. Missing capabilities subtract from the score."""
        healths = self.health()
        healthy = {h.name for h in healths if h.available}

        capabilities = {
            "price_volume": has_price_volume,
            "earnings_calendar": has_earnings,
            "options_chain": has_options,
            "sec_filings": any(p.name in healthy for p in self._filings),
            "news_feed": any(p.name in healthy for p in self._news),
            "macro_data": any(p.name in healthy for p in self._macro),
        }

        score = sum(w for cap, w in _CAPABILITY_WEIGHTS.items() if capabilities.get(cap))
        available = [_label(cap) for cap, on in capabilities.items() if on]
        unavailable = [_label(cap) for cap, on in capabilities.items() if not on]
        unavailable += _KNOWN_UNAVAILABLE

        return DataQualityReport(
            symbol=symbol,
            score=score,
            available=available,
            unavailable=unavailable,
            providers=healths,
        )


def _label(cap: str) -> str:
    return {
        "price_volume": "Price and volume",
        "earnings_calendar": "Earnings calendar",
        "options_chain": "Options chain",
        "sec_filings": "SEC filings",
        "news_feed": "News feed",
        "macro_data": "Macro data",
    }.get(cap, cap)


# Process-wide registry singleton. Providers are registered at app startup.
registry = ProviderRegistry()
