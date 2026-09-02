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

from typing import Optional

UNKNOWN_SECTOR = "Unknown"

# Fallback map, consulted only when sector_cache has no answer. Labels match
# the cache's canonical vocabulary on purpose: the same company reaching a
# different bucket depending on whether the cache is warm would split a sector
# in two and understate concentration.
#
# The ETF entries are the part that earns its keep — yfinance reports no sector
# for a fund, so these pseudo-sectors have no other source. The single-name
# entries are a cold-start fallback for the handful this map ever covered; the
# real coverage now comes from sector_cache over the whole 100-symbol watchlist.
SECTORS: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AMD": "Technology",
    "GOOGL": "Communication Services", "META": "Communication Services",
    "AMZN": "Consumer Cyclical", "TSLA": "Consumer Cyclical",
    "JPM": "Financial Services", "V": "Financial Services", "MA": "Financial Services",
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
    """Resolved sector, or UNKNOWN_SECTOR. Synchronous and never fetches."""
    sym = (ticker or "").upper()
    try:
        from app.services.sector_cache import sector_for_cached
        cached = sector_for_cached(sym)
    except Exception:
        cached = None
    return cached or SECTORS.get(sym, UNKNOWN_SECTOR)


def is_cappable_sector(sector: Optional[str]) -> bool:
    """Whether a sector concentration cap means anything for this bucket.

    "Unknown" is not a sector. It is the absence of one, and the positions in
    it have nothing in common except that nobody classified them. Capping that
    bucket at 40% does not measure concentration — it measures how much of the
    book is unclassified, and then blocks trading on the answer. In production
    on 2026-08-29 it held 94% of the book and produced 179 blocks in 21 days
    naming GILD, AEP, COST, PDD, SBUX and VRTX as one concentrated sector.

    Unknown therefore never blocks. That is deliberately fail-open, against
    this system's usual instinct, because the conservative reading does not
    exist here: an unclassified pair is not *probably* concentrated, and a gate
    that fires on every entry regardless of what it is teaches its operator to
    ignore it. Exposure is still reported, and compute_portfolio_risk() reports
    sector coverage so a thin classification is visible rather than silently
    weakening the check.
    """
    return bool(sector) and sector != UNKNOWN_SECTOR


def compute_portfolio_risk(
    positions: list[dict],
    capital: float,
    max_single_pct: float = 0.25,
    max_sector_pct: float = 0.40,
) -> dict:
    """
    positions: [{"underlying": str, "risk_dollars": float, "sector": str?,
                 "risk_basis": str?}]
    Returns portfolio heat, exposures, concentration flags.

    "risk_basis" is optional and comes from position_risk_basis(). When any
    position reports "notional_no_stop", its risk_dollars is full notional
    rather than a measurement, so the heat derived from it is an overstatement
    — surfaced as risk_basis_counts and heat_overstated rather than left for a
    reader to assume the number means what it says.
    """
    cap = float(capital) if capital and capital > 0 else 0.0
    total_risk = round(sum(float(p.get("risk_dollars", 0) or 0) for p in positions), 2)
    heat = (total_risk / cap) if cap > 0 else 0.0

    basis_counts: dict[str, int] = {}
    for p in positions:
        b = p.get("risk_basis")
        if b:
            basis_counts[b] = basis_counts.get(b, 0) + 1
    unstopped = basis_counts.get("notional_no_stop", 0)

    by_underlying: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    for p in positions:
        u = (p.get("underlying") or "?").upper()
        s = p.get("sector") or sector_for(u)
        r = float(p.get("risk_dollars", 0) or 0)
        by_underlying[u] = round(by_underlying.get(u, 0.0) + r, 2)
        by_sector[s] = round(by_sector.get(s, 0.0) + r, 2)

    largest_u = max(by_underlying.items(), key=lambda x: x[1]) if by_underlying else (None, 0.0)
    # Only real sectors compete to be "largest" for the cap — see
    # is_cappable_sector. The Unknown bucket is still reported below.
    cappable = {k: v for k, v in by_sector.items() if is_cappable_sector(k)}
    largest_s = max(cappable.items(), key=lambda x: x[1]) if cappable else (None, 0.0)
    classified = sum(v for k, v in by_sector.items() if is_cappable_sector(k))

    flags: list[str] = []
    if cap > 0:
        if largest_u[1] / cap > max_single_pct:
            flags.append(f"underlying_concentration:{largest_u[0]} "
                         f"{largest_u[1] / cap:.0%}>{max_single_pct:.0%}")
        if largest_s[0] is not None and largest_s[1] / cap > max_sector_pct:
            flags.append(f"sector_concentration:{largest_s[0]} "
                         f"{largest_s[1] / cap:.0%}>{max_sector_pct:.0%}")

    heat_status = "high" if heat > HEAT_HIGH else "elevated" if heat > HEAT_ELEVATED else "ok"

    return {
        "position_count": len(positions),
        "capital": round(cap, 2),
        "total_risk_dollars": total_risk,
        "portfolio_heat_pct": round(heat * 100, 2),
        "heat_status": heat_status,
        "risk_basis_counts": basis_counts,
        "unstopped_position_count": unstopped,
        # How much of the book the sector cap can actually see. A low number
        # means the check is weak, which is worth showing rather than hiding
        # behind an Unknown bucket that blocks everything instead.
        "sector_classified_pct": (round(classified / total_risk * 100, 2)
                                  if total_risk > 0 else 0.0),
        "unclassified_sector_dollars": round(
            by_sector.get(UNKNOWN_SECTOR, 0.0), 2),
        # True when at least one position contributed notional instead of a
        # measured stop distance, so heat is an upper bound, not a reading.
        "heat_overstated": unstopped > 0,
        "largest_underlying": largest_u[0],
        "largest_underlying_pct": round((largest_u[1] / cap * 100), 2) if cap > 0 else 0.0,
        "largest_sector": largest_s[0],
        "largest_sector_pct": round((largest_s[1] / cap * 100), 2) if cap > 0 else 0.0,
        "exposure_by_underlying": dict(sorted(by_underlying.items(), key=lambda x: -x[1])),
        "exposure_by_sector": dict(sorted(by_sector.items(), key=lambda x: -x[1])),
        "concentration_flags": flags,
    }


def _is_equity(trade) -> bool:
    spread_type = (getattr(trade, "spread_type", "") or "").lower()
    return spread_type.startswith("equity") or getattr(trade, "strategy", "") == "equity"


def equity_stop_distance(trade) -> Optional[float]:
    """Per-share distance from entry to the protective stop, or None.

    The stop is already on the row: trade_desk.py's equity entry path stores
    trade_plan["entry_price"] in short_strike and trade_plan["stop_price"] in
    long_strike (credit_received carries the entry price again). No new column
    is needed to measure real risk — only a careful read of the one we have.

    Returns None whenever the row does not carry a *trustworthy* stop, because
    the alternative is far worse than the overstatement this function exists to
    fix. Rows adopted by the reconciler (main.py::_adopt_untracked_positions)
    write the live avg_cost into all three price fields as discovery-time
    placeholders, so entry == stop; reading that literally yields a stop
    distance of zero and a position that appears to risk nothing at all.
    Confirmed on production 2026-08-29: LITE and MSTR both had entry == stop
    == 887.22 / 126.95, which would have measured as $0.20 and $0.12 of risk
    against $60,331 and $19,804 of notional. Understating risk is the
    dangerous direction to be wrong in, so an untrustworthy stop is reported
    as absent rather than believed.

    Three ways a stop fails to be trustworthy:
      - it is missing or non-positive;
      - it sits within 0.1% of entry (a placeholder, not a stop — a real stop
        from compute_equity_trade_plan is entry ± 2xATR, never adjacent to it);
      - it is on the wrong side of entry for the position's direction, which
        means the row's fields do not mean what this function assumes.
    """
    if not _is_equity(trade):
        return None
    entry = float(getattr(trade, "credit_received", 0) or 0)
    stop = float(getattr(trade, "long_strike", 0) or 0)
    if entry <= 0 or stop <= 0:
        return None
    distance = abs(entry - stop)
    if distance < 0.001 * entry:
        return None
    is_short = (getattr(trade, "spread_type", "") or "").lower() == "equity_short"
    # Long stops sit below entry, short stops above. Either way round means the
    # row is not shaped the way this read assumes — do not guess at it.
    if is_short and stop < entry:
        return None
    if not is_short and stop > entry:
        return None
    return distance


def position_risk_basis(trade) -> str:
    """How position_risk_dollars() arrived at its number, for honest reporting.

      - "defined_max_loss"  — options; the structure caps the loss exactly.
      - "stop_distance"     — equity with a real stop; true risk-at-stake.
      - "notional_no_stop"  — equity with no trustworthy stop; the number is
                              full notional, a deliberate overstatement.
    """
    if not _is_equity(trade):
        return "defined_max_loss"
    return "stop_distance" if equity_stop_distance(trade) is not None else "notional_no_stop"


def position_risk_dollars(trade) -> float:
    """
    Derive risk-at-stake from an open Trade row.
      - Credit spread: defined max loss = (width − credit) × 100 × qty.
      - Debit spread (bull_call_debit_spread; credit_received is negative —
        see backtester.py's entry-side convention): max loss is simply the
        debit paid, not width-minus-credit — that formula would add the debit
        to the width instead of isolating it as the actual capital at risk.
      - Equity with a stop: |entry − stop| × shares — what is actually at risk.
      - Equity without a trustworthy stop: notional = entry × shares. A
        deliberate overstatement, reported as "notional_no_stop" by
        position_risk_basis() so no caller mistakes it for a measurement.

    Until 2026-08-29 every equity position used the notional branch
    unconditionally. Its own comment called that a worst-case proxy, but heat
    and both concentration checks consumed it as if it were risk: production
    read 94.06% heat on a book that was simply invested, and the resulting
    concentration blocks were real — 179 of them in the preceding 21 days.
    """
    qty = int(getattr(trade, "quantity", None) or 1)
    credit = float(getattr(trade, "credit_received", 0) or 0)
    if _is_equity(trade):
        stop_distance = equity_stop_distance(trade)
        if stop_distance is None:
            return round(credit * qty, 2)       # notional — no stop to measure
        return round(stop_distance * qty, 2)    # real risk-at-stake
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
