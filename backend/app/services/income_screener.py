"""
Income Matrix screener — Options-Matrix-Pro-style premium-income discovery.

For each watchlist symbol it scans the option chain for the best premium-selling
income setups — cash-secured puts (CSP) and covered calls (CC) — and reports
standardized yield metrics (per-trade %, monthly %, annualized %), capital
required, breakeven, and probability the option expires OTM (i.e. the seller
keeps the premium). A snapshot from free yfinance data, not a real-time feed.

Pure helpers (prob_otm / csp_row / cc_row) carry the math and are unit tested;
scan_income_matrix is the thin yfinance I/O wrapper.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from scipy.stats import norm


def prob_otm(spot: float, strike: float, dte: float, iv: float, *, is_put: bool,
             r: float = 0.04) -> float:
    """
    Probability the option finishes out-of-the-money (seller keeps premium),
    via Black-Scholes d2. Put expires OTM if S_T > K → N(d2); call if S_T < K → N(-d2).
    """
    T = max(dte, 0.0) / 365.0
    if spot <= 0 or strike <= 0 or iv <= 0 or T <= 0:
        return 0.0
    d2 = (math.log(spot / strike) + (r - 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
    return float(norm.cdf(d2) if is_put else norm.cdf(-d2))


def _yields(premium: float, capital_per_share: float, dte: float) -> dict:
    """Per-trade / monthly / annualized yield on the capital tied up."""
    base = premium / capital_per_share if capital_per_share > 0 else 0.0
    d = max(dte, 1.0)
    return {
        "return_pct":            round(base * 100, 2),
        "monthly_return_pct":    round(base * (30.0 / d) * 100, 2),
        "annualized_return_pct": round(base * (365.0 / d) * 100, 2),
    }


def csp_row(*, ticker: str, strike: float, expiry: str, dte: int,
            spot: Optional[float], premium: float, iv: Optional[float]) -> dict:
    """Cash-secured put: collateral = strike×100; yield is premium/strike."""
    y = _yields(premium, strike, dte)
    return {
        "ticker":            ticker.upper(),
        "strategy":          "cash_secured_put",
        "type":              "PUT",
        "strike":            round(float(strike), 2),
        "expiry":            expiry,
        "dte":               dte,
        "spot":              round(float(spot), 2) if spot is not None else None,
        "premium":           round(float(premium), 2),
        "capital_required":  round(float(strike) * 100, 2),
        "breakeven":         round(float(strike) - float(premium), 2),
        "prob_otm":          round(prob_otm(spot or 0, strike, dte, iv or 0, is_put=True), 4)
                             if (spot and iv) else None,
        **y,
    }


def cc_row(*, ticker: str, strike: float, expiry: str, dte: int,
           spot: Optional[float], premium: float, iv: Optional[float]) -> dict:
    """Covered call: collateral = 100 shares (≈spot×100); yield is premium/spot."""
    base = float(spot) if spot else float(strike)
    y = _yields(premium, base, dte)
    return {
        "ticker":            ticker.upper(),
        "strategy":          "covered_call",
        "type":              "CALL",
        "strike":            round(float(strike), 2),
        "expiry":            expiry,
        "dte":               dte,
        "spot":              round(float(spot), 2) if spot is not None else None,
        "premium":           round(float(premium), 2),
        "capital_required":  round(base * 100, 2),
        "breakeven":         round(base - float(premium), 2),
        "prob_otm":          round(prob_otm(spot or 0, strike, dte, iv or 0, is_put=False), 4)
                             if (spot and iv) else None,
        **y,
    }


# ── yfinance I/O (thin wrapper + TTL cache) ─────────────────────────────────────
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300


async def scan_income_matrix(   # pragma: no cover - yfinance network I/O
    tickers: list[str], *,
    max_tickers: int = 10,
    max_expiries: int = 3,
    min_premium: float = 0.10,
    min_prob_otm: float = 0.60,
    top: int = 200,
) -> list[dict]:
    """
    Scan watchlist chains for the best CSP / covered-call income setups, sorted by
    annualized return (desc). Cached for _CACHE_TTL seconds.
    """
    key = f"income:{','.join(tickers[:max_tickers])}"
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
                if not spot:
                    continue
                for exp in list(getattr(tk, "options", []) or [])[:max_expiries]:
                    try:
                        chain = tk.option_chain(exp)
                    except Exception:
                        continue
                    try:
                        dte = (_date.fromisoformat(exp) - _date.today()).days
                    except Exception:
                        dte = 0
                    if dte < 0:
                        continue
                    # CSP: out-of-the-money puts (strike below spot)
                    for _, r in chain.puts.iterrows():
                        prem = float(r.get("bid") or r.get("lastPrice") or 0)
                        strike = float(r.get("strike") or 0)
                        if strike <= 0 or strike >= spot or prem < min_premium:
                            continue
                        row = csp_row(ticker=sym, strike=strike, expiry=exp, dte=dte,
                                      spot=spot, premium=prem,
                                      iv=float(r.get("impliedVolatility") or 0) or None)
                        if (row["prob_otm"] or 0) >= min_prob_otm:
                            rows.append(row)
                    # Covered call: out-of-the-money calls (strike above spot)
                    for _, r in chain.calls.iterrows():
                        prem = float(r.get("bid") or r.get("lastPrice") or 0)
                        strike = float(r.get("strike") or 0)
                        if strike <= spot or prem < min_premium:
                            continue
                        row = cc_row(ticker=sym, strike=strike, expiry=exp, dte=dte,
                                     spot=spot, premium=prem,
                                     iv=float(r.get("impliedVolatility") or 0) or None)
                        if (row["prob_otm"] or 0) >= min_prob_otm:
                            rows.append(row)
            except Exception:
                continue
        rows.sort(key=lambda x: x["annualized_return_pct"], reverse=True)
        return rows

    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _scan)
    _CACHE[key] = (now, rows)
    return rows[:top]
