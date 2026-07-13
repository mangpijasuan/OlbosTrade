"""
Portfolio Engine — heat, exposure and concentration.

Aggregates risk-at-stake across open positions into a single "portfolio heat"
(% of capital at risk) plus per-underlying and per-sector exposure, and flags
concentration breaches. Pure aggregation so it's fully testable; callers supply
each position's risk in dollars.

(VaR / Expected Shortfall / Monte Carlo are intentionally deferred until there is
enough position + correlation history to make them meaningful rather than noise.)
"""

from __future__ import annotations

# Lightweight static sector map for the common watchlist. "Unknown" otherwise.
SECTORS: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AMD": "Technology",
    "GOOGL": "Communication", "META": "Communication",
    "AMZN": "Consumer", "TSLA": "Consumer",
    "JPM": "Financials", "V": "Financials", "MA": "Financials",
    "SPY": "Index", "QQQ": "Index", "IWM": "Index",
    "TLT": "Bonds", "GLD": "Commodity", "USO": "Commodity", "UUP": "Dollar",
    "BIL": "Cash",
}

HEAT_ELEVATED = 0.30   # >30% of capital at risk
HEAT_HIGH = 0.50       # >50% of capital at risk


def sector_for(ticker: str) -> str:
    return SECTORS.get((ticker or "").upper(), "Unknown")


def compute_portfolio_risk(
    positions: list[dict],
    capital: float,
    max_single_pct: float = 0.25,
    max_sector_pct: float = 0.40,
) -> dict:
    """
    positions: [{"underlying": str, "risk_dollars": float, "sector": str?}]
    Returns portfolio heat, exposures, concentration flags.
    """
    cap = float(capital) if capital and capital > 0 else 0.0
    total_risk = round(sum(float(p.get("risk_dollars", 0) or 0) for p in positions), 2)
    heat = (total_risk / cap) if cap > 0 else 0.0

    by_underlying: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    for p in positions:
        u = (p.get("underlying") or "?").upper()
        s = p.get("sector") or sector_for(u)
        r = float(p.get("risk_dollars", 0) or 0)
        by_underlying[u] = round(by_underlying.get(u, 0.0) + r, 2)
        by_sector[s] = round(by_sector.get(s, 0.0) + r, 2)

    largest_u = max(by_underlying.items(), key=lambda x: x[1]) if by_underlying else (None, 0.0)
    largest_s = max(by_sector.items(), key=lambda x: x[1]) if by_sector else (None, 0.0)

    flags: list[str] = []
    if cap > 0:
        if largest_u[1] / cap > max_single_pct:
            flags.append(f"underlying_concentration:{largest_u[0]} "
                         f"{largest_u[1] / cap:.0%}>{max_single_pct:.0%}")
        if largest_s[1] / cap > max_sector_pct:
            flags.append(f"sector_concentration:{largest_s[0]} "
                         f"{largest_s[1] / cap:.0%}>{max_sector_pct:.0%}")

    heat_status = "high" if heat > HEAT_HIGH else "elevated" if heat > HEAT_ELEVATED else "ok"

    return {
        "position_count": len(positions),
        "capital": round(cap, 2),
        "total_risk_dollars": total_risk,
        "portfolio_heat_pct": round(heat * 100, 2),
        "heat_status": heat_status,
        "largest_underlying": largest_u[0],
        "largest_underlying_pct": round((largest_u[1] / cap * 100), 2) if cap > 0 else 0.0,
        "largest_sector": largest_s[0],
        "largest_sector_pct": round((largest_s[1] / cap * 100), 2) if cap > 0 else 0.0,
        "exposure_by_underlying": dict(sorted(by_underlying.items(), key=lambda x: -x[1])),
        "exposure_by_sector": dict(sorted(by_sector.items(), key=lambda x: -x[1])),
        "concentration_flags": flags,
    }


def position_risk_dollars(trade) -> float:
    """
    Derive risk-at-stake from an open Trade row.
      - Credit spread: defined max loss = (width − credit) × 100 × qty.
      - Debit spread (bull_call_debit_spread; credit_received is negative —
        see backtester.py's entry-side convention): max loss is simply the
        debit paid, not width-minus-credit — that formula would add the debit
        to the width instead of isolating it as the actual capital at risk.
      - Equity: notional = entry_price × shares (worst-case proxy).
    """
    qty = int(getattr(trade, "quantity", None) or 1)
    spread_type = (getattr(trade, "spread_type", "") or "").lower()
    credit = float(getattr(trade, "credit_received", 0) or 0)
    if spread_type.startswith("equity") or getattr(trade, "strategy", "") == "equity":
        return round(credit * qty, 2)   # entry price × shares
    if credit < 0:
        return round(abs(credit) * 100 * qty, 2)
    short_k = float(getattr(trade, "short_strike", 0) or 0)
    long_k = float(getattr(trade, "long_strike", 0) or 0)
    width = abs(short_k - long_k)
    return round(max(width - credit, 0.0) * 100 * qty, 2)
