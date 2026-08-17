"""
Sector Rotation — relative-strength ranking table (docs/trade-desk-2.0/
MASTER_SPEC.md:74 lists this under Markets with no further design detail;
the ranking-table shape below was confirmed with the user).

The 11 GICS sector ETFs, ranked by trailing return across a few timeframes.
Rank-change is derived honestly from the same bars fetch (comparing today's
ranking to the ranking as of 5 trading days ago) rather than a persisted
snapshot — no new table, no background job.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLC": "Communication Services",
}

TIMEFRAMES: dict[str, int] = {"1D": 1, "1W": 5, "1M": 21, "3M": 63}

RANK_CHANGE_LOOKBACK_DAYS = 5
_BARS_LIMIT = 75  # 3M offset (63) + rank-change lookback (5) + margin


def compute_returns(closes: list[float]) -> dict[str, Optional[float]]:
    """Pure. Returns None per timeframe when there isn't enough history —
    never fabricates a 0% return for missing data."""
    out: dict[str, Optional[float]] = {}
    for label, offset in TIMEFRAMES.items():
        if len(closes) > offset and closes[-1 - offset] != 0:
            out[label] = (closes[-1] - closes[-1 - offset]) / closes[-1 - offset]
        else:
            out[label] = None
    return out


def rank_sectors(returns_by_ticker: dict[str, dict[str, Optional[float]]], basis: str = "1M") -> dict[str, Optional[int]]:
    """Pure. Ranks tickers descending by returns_by_ticker[t][basis]; tickers
    missing that timeframe get None (excluded from ranking, not placed last
    as if ranked)."""
    rankable = sorted(
        (t for t, r in returns_by_ticker.items() if r.get(basis) is not None),
        key=lambda t: -returns_by_ticker[t][basis],
    )
    ranks: dict[str, Optional[int]] = {t: None for t in returns_by_ticker}
    for i, t in enumerate(rankable, start=1):
        ranks[t] = i
    return ranks


async def _fetch_closes(ticker: str) -> list[float]:
    """Daily close prices, oldest first. Never raises — a failed fetch
    returns [] so one bad symbol can't break the whole response."""
    import yfinance as yf

    def _fetch():
        hist = yf.Ticker(ticker).history(period=f"{min(_BARS_LIMIT * 2, 365)}d", auto_adjust=True)
        return hist.tail(_BARS_LIMIT)

    loop = asyncio.get_running_loop()
    try:
        hist = await loop.run_in_executor(None, _fetch)
        closes = [float(c) for c in hist["Close"].tolist() if c == c]  # drop NaN
        return closes
    except Exception as exc:
        logger.warning("sector_rotation: failed to fetch bars for %s: %s", ticker, exc)
        return []


async def get_sector_rotation(rank_basis: str = "1M") -> dict:
    from datetime import datetime, timezone

    sem = asyncio.Semaphore(5)
    excluded: list[dict] = []

    async def _resolve(ticker: str) -> tuple[str, list[float]]:
        async with sem:
            closes = await _fetch_closes(ticker)
            if not closes:
                excluded.append({"ticker": ticker, "name": SECTOR_ETFS[ticker], "reason": "no data returned"})
            return ticker, closes

    resolved = await asyncio.gather(*(_resolve(t) for t in SECTOR_ETFS))
    closes_by_ticker = {t: c for t, c in resolved if c}

    current_returns: dict[str, dict[str, Optional[float]]] = {
        t: compute_returns(c) for t, c in closes_by_ticker.items()
    }
    prior_returns: dict[str, dict[str, Optional[float]]] = {
        t: compute_returns(c[:-RANK_CHANGE_LOOKBACK_DAYS])
        for t, c in closes_by_ticker.items()
        if len(c) > RANK_CHANGE_LOOKBACK_DAYS
    }

    current_rank = rank_sectors(current_returns, rank_basis)
    prior_rank = rank_sectors(prior_returns, rank_basis) if prior_returns else {}

    sectors = []
    for t in closes_by_ticker:
        rc = None
        if current_rank.get(t) is not None and prior_rank.get(t) is not None:
            rc = prior_rank[t] - current_rank[t]
        sectors.append({
            "ticker": t,
            "name": SECTOR_ETFS[t],
            "returns": current_returns[t],
            "rank": current_rank.get(t),
            "prior_rank": prior_rank.get(t),
            "rank_change": rc,
        })

    sectors.sort(key=lambda s: (s["rank"] is None, s["rank"] if s["rank"] is not None else 0))

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "rank_basis": rank_basis,
        "sectors": sectors,
        "excluded": excluded,
        "data_source": "yfinance daily bars",
    }
