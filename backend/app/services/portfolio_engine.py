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

# Correlation Clusters — positions whose daily returns move together enough
# to behave as one concentrated position rather than diversified risk.
CORRELATION_THRESHOLD = 0.70    # signed, not abs() — see compute_correlation_clusters
CORRELATION_MIN_BARS = 30       # matches equity_signal_engine.compute_indicators' own cutoff
CORRELATION_MAX_CLUSTER_PCT = 0.40


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


def align_price_series(
    bars_by_ticker: dict[str, list],
    min_bars: int = CORRELATION_MIN_BARS,
) -> tuple[dict[str, list[float]], list[dict]]:
    """
    bars_by_ticker: {ticker: [Bar, ...]} (Bar has .timestamp, .close).
    Drops tickers with fewer than min_bars, then intersects the remaining
    tickers' calendar dates so every series is equal-length and aligned
    day-for-day (not just truncated to a common length, which could pair
    up unrelated dates across tickers with different missing sessions).
    Returns (aligned_closes, excluded) where excluded is
    [{"ticker": str, "reason": str}, ...].
    """
    excluded: list[dict] = []
    by_date: dict[str, dict] = {}
    for ticker, bars in bars_by_ticker.items():
        if len(bars) < min_bars:
            excluded.append({
                "ticker": ticker,
                "reason": f"only {len(bars)} bars, need >= {min_bars}",
            })
            continue
        by_date[ticker] = {b.timestamp.date(): float(b.close) for b in bars}

    if len(by_date) < 2:
        return {}, excluded

    common_dates = set.intersection(*(set(d.keys()) for d in by_date.values()))
    if len(common_dates) < min_bars:
        for ticker in by_date:
            excluded.append({
                "ticker": ticker,
                "reason": f"only {len(common_dates)} overlapping trading days, need >= {min_bars}",
            })
        return {}, excluded

    ordered_dates = sorted(common_dates)
    aligned = {
        ticker: [dates[d] for d in ordered_dates]
        for ticker, dates in by_date.items()
    }
    return aligned, excluded


def compute_correlation_clusters(
    aligned_closes: dict[str, list[float]],
    threshold: float = CORRELATION_THRESHOLD,
) -> dict:
    """
    aligned_closes: {ticker: [close, ...]} — equal length, already aligned
    (see align_price_series). Computes daily-return Pearson correlation and
    groups tickers into clusters via union-find over pairs whose *signed*
    correlation is >= threshold (negative correlation is hedging, not
    concentration, and must never be treated as a cluster edge).
    """
    import pandas as pd

    tickers = sorted(aligned_closes.keys())
    if len(tickers) < 2:
        return {
            "tickers": tickers,
            "correlation_matrix": {},
            "clusters": [],
            "threshold": threshold,
        }

    returns = pd.DataFrame({t: aligned_closes[t] for t in tickers}).pct_change().dropna()
    corr = returns.corr()
    correlation_matrix = {
        row: {col: round(float(corr.loc[row, col]), 4) for col in tickers}
        for row in tickers
    }

    parent = {t: t for t in tickers}

    def find(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            if corr.loc[a, b] >= threshold:
                union(a, b)

    groups: dict[str, list[str]] = {}
    for t in tickers:
        groups.setdefault(find(t), []).append(t)

    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        pairs = [
            corr.loc[a, b]
            for i, a in enumerate(members)
            for b in members[i + 1:]
        ]
        avg_corr = round(float(sum(pairs) / len(pairs)), 4) if pairs else 0.0
        clusters.append({"tickers": sorted(members), "avg_correlation": avg_corr})

    clusters.sort(key=lambda c: -c["avg_correlation"])

    return {
        "tickers": tickers,
        "correlation_matrix": correlation_matrix,
        "clusters": clusters,
        "threshold": threshold,
    }


def cluster_concentration_flags(
    clusters: list[dict],
    risk_dollars_by_underlying: dict[str, float],
    capital: float,
    max_cluster_pct: float = CORRELATION_MAX_CLUSTER_PCT,
) -> tuple[list[dict], list[str]]:
    """
    Enriches each cluster with combined_risk_dollars/pct_of_capital and
    emits a concentration flag string (matching this file's existing
    "underlying_concentration:"/"sector_concentration:" format) for any
    cluster whose combined risk exceeds max_cluster_pct of capital.
    """
    cap = float(capital) if capital and capital > 0 else 0.0
    enriched: list[dict] = []
    flags: list[str] = []

    for cluster in clusters:
        combined = round(
            sum(float(risk_dollars_by_underlying.get(t, 0.0) or 0.0) for t in cluster["tickers"]),
            2,
        )
        pct = (combined / cap) if cap > 0 else 0.0
        entry = {**cluster, "combined_risk_dollars": combined, "pct_of_capital": round(pct * 100, 2)}
        enriched.append(entry)
        if cap > 0 and pct > max_cluster_pct:
            joined = "+".join(cluster["tickers"])
            flags.append(f"correlation_concentration:{joined} {pct:.0%}>{max_cluster_pct:.0%}")

    return enriched, flags
