"""
Unusual Options Activity — a free options-flow approximation from yfinance.

A true OPRA flow tape (timestamped sweeps/blocks like optionsflow.com) needs a
paid market-data feed. As a free stand-in, we pull each watchlist symbol's option
chain and flag contracts whose **traded volume is large and well above open
interest** — the classic "unusual activity" signal that new positioning is being
opened. This is a periodic SNAPSHOT (not tick-by-tick) and has no true buy/sell
side, so sentiment is inferred from contract type (calls=bullish, puts=bearish).

The pure helpers (is_unusual / flow_row / summarize) carry the logic and are unit
tested; scan_unusual_activity is the thin yfinance I/O wrapper with a TTL cache.
"""

from __future__ import annotations

import time
from typing import Optional


def is_unusual(volume: Optional[float], open_interest: Optional[float], *,
               min_volume: int = 200, ratio: float = 2.0) -> bool:
    """True if a contract's volume is both sizeable and well above open interest."""
    v = float(volume or 0)
    oi = float(open_interest or 0)
    if v < min_volume:
        return False
    # New OI (oi==0) with real volume is unusual by definition; else require ratio.
    return v >= ratio * oi if oi > 0 else True


def flow_row(*, ticker: str, opt_type: str, strike: float, expiry: str,
             spot: Optional[float], volume: Optional[float],
             open_interest: Optional[float], last_price: Optional[float],
             iv: Optional[float], dte: Optional[int]) -> dict:
    """Build one normalized flow row (premium estimate, vol/OI, sentiment)."""
    v = int(volume or 0)
    oi = int(open_interest or 0)
    last = float(last_price or 0.0)
    # Estimated notional premium traded today: volume × last × 100 multiplier.
    premium = round(v * last * 100, 2)
    vol_oi = round(v / oi, 2) if oi > 0 else None
    is_call = opt_type.lower().startswith("c")
    return {
        "ticker":        ticker.upper(),
        "type":          "CALL" if is_call else "PUT",
        "strike":        round(float(strike), 2),
        "expiry":        expiry,
        "dte":           dte,
        "spot":          round(float(spot), 2) if spot is not None else None,
        "volume":        v,
        "open_interest": oi,
        "vol_oi_ratio":  vol_oi,
        "last_price":    round(last, 2),
        "iv":            round(float(iv), 4) if iv is not None else None,
        "premium":       premium,
        "sentiment":     "bullish" if is_call else "bearish",
    }


def summarize(rows: list[dict]) -> dict:
    """Aggregate call/put premium and a net bullish ratio (0.5 = neutral)."""
    call_prem = sum(r["premium"] for r in rows if r["type"] == "CALL")
    put_prem  = sum(r["premium"] for r in rows if r["type"] == "PUT")
    total = call_prem + put_prem
    return {
        "count":          len(rows),
        "call_premium":   round(call_prem, 2),
        "put_premium":    round(put_prem, 2),
        "net_premium":    round(call_prem - put_prem, 2),
        "bullish_ratio":  round(call_prem / total, 4) if total > 0 else 0.5,
    }


# ── yfinance I/O (thin wrapper + TTL cache) ─────────────────────────────────────
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300  # seconds


async def scan_unusual_activity(   # pragma: no cover - yfinance network I/O
    tickers: list[str], *,
    max_tickers: int = 8,
    max_expiries: int = 2,
    min_volume: int = 200,
    ratio: float = 2.0,
    top: int = 150,
) -> list[dict]:
    """
    Scan watchlist option chains for unusual activity. Returns flow rows sorted by
    estimated premium (desc). Cached for _CACHE_TTL seconds (yfinance is slow).
    """
    key = ",".join(tickers[:max_tickers])
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1][:top]

    import asyncio
    from datetime import date as _date
    import yfinance as yf

    def _scan() -> list[dict]:
        rows: list[dict] = []
        for sym in tickers[:max_tickers]:
            try:
                tk = yf.Ticker(sym)
                try:
                    spot = float(tk.fast_info["last_price"])
                except Exception:
                    h = tk.history(period="1d")
                    spot = float(h["Close"].iloc[-1]) if not h.empty else None
                expiries = list(getattr(tk, "options", []) or [])[:max_expiries]
                for exp in expiries:
                    try:
                        chain = tk.option_chain(exp)
                    except Exception:
                        continue
                    dte = None
                    try:
                        dte = (_date.fromisoformat(exp) - _date.today()).days
                    except Exception:
                        pass
                    for df, opt_type in ((chain.calls, "call"), (chain.puts, "put")):
                        for _, r in df.iterrows():
                            if not is_unusual(r.get("volume"), r.get("openInterest"),
                                              min_volume=min_volume, ratio=ratio):
                                continue
                            rows.append(flow_row(
                                ticker=sym, opt_type=opt_type,
                                strike=r.get("strike", 0), expiry=exp, spot=spot,
                                volume=r.get("volume"), open_interest=r.get("openInterest"),
                                last_price=r.get("lastPrice"),
                                iv=r.get("impliedVolatility"), dte=dte,
                            ))
            except Exception:
                continue
        rows.sort(key=lambda x: x["premium"], reverse=True)
        return rows

    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _scan)
    _CACHE[key] = (now, rows)
    return rows[:top]
