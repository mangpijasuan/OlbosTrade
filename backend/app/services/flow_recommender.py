"""
Flow Recommender — turns Unusual Options Activity + Live Signals into structured
"Setup Recommendations".

Pipeline:
  raw flow rows (unusual_activity.flow_row shape, optionally with an order `side`)
    → filter (vol/OI, short-dated DTE, aggressive side)
    → cluster per (ticker, direction)  [premium concentration + gamma magnet]
    → confluence check vs a per-ticker technical bias (Live Signals / regime)
    → conviction score (1-10) + structured Recommendation Setup

Design:
  - The pure helpers (safe_vol_oi / conviction_score / pick_strategy / cluster_flow
    / build_recommendation / recommend) hold all logic and are unit tested.
  - generate_recommendations is the thin async orchestrator that pulls live flow
    (unusual_activity) and the bias map (recent equity signals) and calls recommend().

Edge cases:
  - Open Interest == 0 never divides by zero — it's treated as *fresh* positioning
    (no prior OI), the strongest unusual signal, with vol_oi_ratio reported as null
    and a `new_position` flag set.
  - Missing/None numeric fields default to 0 and are filtered out, never crash.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

# Flow direction → market direction.
_DIR = {"CALL": "BULLISH", "PUT": "BEARISH"}


def safe_vol_oi(volume, open_interest) -> tuple[Optional[float], bool]:
    """
    Return (ratio, new_position). Never divides by zero:
      - OI > 0  → (volume/OI, False)
      - OI == 0 and volume > 0 → (None, True)  ← fresh positioning, no prior OI
      - otherwise → (0.0, False)
    """
    v = float(volume or 0)
    oi = float(open_interest or 0)
    if oi > 0:
        return round(v / oi, 2), False
    if v > 0:
        return None, True   # brand-new strike — treat as maximally unusual
    return 0.0, False


def _passes_filters(row: dict, *, min_vol_oi: float, max_dte: int,
                    min_row_premium: float) -> bool:
    """Per-contract gate before clustering."""
    dte = row.get("dte")
    if dte is None or dte > max_dte or dte < 0:
        return False
    if float(row.get("premium") or 0) < min_row_premium:
        return False
    ratio, new_pos = safe_vol_oi(row.get("volume"), row.get("open_interest"))
    if new_pos:
        return True                      # OI==0 with volume → always interesting
    return (ratio or 0) >= min_vol_oi


def _aggressive(side: Optional[str]) -> Optional[str]:
    """Normalize order side. ASK = buyer-initiated (long/debit), BID = seller (credit)."""
    if not side:
        return None
    s = str(side).upper()
    if s in ("ASK", "A", "BUY"):
        return "ASK"
    if s in ("BID", "B", "SELL"):
        return "BID"
    return None   # MID / unknown → neutral


def pick_strategy(direction: str, dte: Optional[int], side: Optional[str]) -> str:
    """Map direction + DTE + order side to a concrete strategy label."""
    long_setup = _aggressive(side) == "ASK"        # buying premium = directional/momentum
    zero = dte is not None and dte <= 0
    if direction == "BULLISH":
        if zero:
            return "0DTE Momentum (Long Call)" if long_setup else "0DTE Bull Put Spread"
        return "Long Call" if long_setup else "Bull Put Spread"
    # BEARISH
    if zero:
        return "0DTE Momentum (Long Put)" if long_setup else "0DTE Bear Call Spread"
    return "Long Put" if long_setup else "Bear Call Spread"


def conviction_score(*, vol_oi: Optional[float], new_position: bool,
                     premium: float, premium_floor: float,
                     confluent: bool, aggressive: bool) -> int:
    """
    1-10 conviction. vol/OI magnitude (0-4) + premium size (0-3) + technical
    confluence (0-2) + aggressive order side (0-1). OI==0 (new positioning) gets
    full vol/OI weight.
    """
    if new_position:
        ratio_pts = 4.0
    else:
        ratio_pts = min((vol_oi or 0) / 10.0, 1.0) * 4.0
    prem_pts = min(premium / premium_floor, 1.0) * 3.0 if premium_floor > 0 else 0.0
    conf_pts = 2.0 if confluent else 0.0
    side_pts = 1.0 if aggressive else 0.0
    return max(1, min(10, round(ratio_pts + prem_pts + conf_pts + side_pts)))


def cluster_flow(rows: list[dict]) -> dict[tuple, dict]:
    """
    Aggregate filtered rows into (ticker, direction) clusters:
      total_premium, total_volume, max vol/OI, gamma_magnet (highest-volume strike),
      target_strike (highest-premium strike), and a representative spot/expiry/dte/side.
    """
    clusters: dict[tuple, dict] = {}
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        direction = _DIR.get(r.get("type", ""))
        if direction is None:
            continue
        by_key[(r["ticker"], direction)].append(r)

    for (ticker, direction), group in by_key.items():
        total_premium = sum(float(r.get("premium") or 0) for r in group)
        total_volume = sum(int(r.get("volume") or 0) for r in group)
        gamma_row = max(group, key=lambda r: int(r.get("volume") or 0))
        target_row = max(group, key=lambda r: float(r.get("premium") or 0))
        ratios = [safe_vol_oi(r.get("volume"), r.get("open_interest")) for r in group]
        new_position = any(n for _, n in ratios)
        numeric_ratios = [x for x, _ in ratios if x is not None]
        max_vol_oi = max(numeric_ratios) if numeric_ratios else None
        clusters[(ticker, direction)] = {
            "ticker": ticker,
            "direction": direction,
            "total_premium": round(total_premium, 2),
            "total_volume": total_volume,
            "max_vol_oi": max_vol_oi,
            "new_position": new_position,
            "gamma_magnet": gamma_row.get("strike"),
            "target_strike": target_row.get("strike"),
            "spot": target_row.get("spot"),
            "expiry": target_row.get("expiry"),
            "dte": target_row.get("dte"),
            "side": target_row.get("side"),
            "contracts": len(group),
        }
    return clusters


def build_recommendation(cluster: dict, bias: Optional[str], *,
                         premium_floor: float, entry_band_pct: float = 0.5) -> dict:
    """Build one structured Recommendation Setup from a cluster + technical bias."""
    direction = cluster["direction"]
    dte = cluster.get("dte")
    side = cluster.get("side")
    spot = cluster.get("spot")

    # Confluence: does the technical bias confirm the flow's direction?
    if bias in ("BULLISH", "BEARISH"):
        confluence = "confirmed" if bias == direction else "divergent"
    else:
        confluence = "neutral"

    score = conviction_score(
        vol_oi=cluster.get("max_vol_oi"),
        new_position=cluster.get("new_position", False),
        premium=cluster.get("total_premium", 0.0),
        premium_floor=premium_floor,
        confluent=(confluence == "confirmed"),
        aggressive=_aggressive(side) is not None,
    )
    # A directional conflict with the technicals caps conviction.
    if confluence == "divergent":
        score = min(score, 4)

    long_setup = _aggressive(side) == "ASK"
    if spot is not None:
        lo = round(spot * (1 - entry_band_pct / 100), 2)
        hi = round(spot * (1 + entry_band_pct / 100), 2)
        entry_zone = f"{lo}–{hi} (spot {spot} ±{entry_band_pct}%)"
    else:
        entry_zone = f"Current spot ±{entry_band_pct}%"

    if long_setup:
        stop = "Exit if option premium decays ~50%, or underlying closes back through entry zone."
        take = "Scale out at +50–100% premium, or when short-leg delta ≈ 0.50."
    else:  # credit / spread
        stop = "Close at ~2× credit received, or if the short strike is breached."
        take = "Close at 50% of max profit (theta capture)."

    return {
        "ticker": cluster["ticker"],
        "direction": direction,
        "strategy_type": pick_strategy(direction, dte, side),
        "setup_details": {
            "target_strike": cluster.get("target_strike"),
            "expiration": cluster.get("expiry"),
            "entry_zone": entry_zone,
            "estimated_gamma_magnet": cluster.get("gamma_magnet"),
        },
        "risk_management": {
            "suggested_stop_loss": stop,
            "suggested_take_profit": take,
        },
        "conviction_score": score,
        "confluence": confluence,
        "flow_summary": {
            "total_premium": cluster.get("total_premium"),
            "total_volume": cluster.get("total_volume"),
            "max_vol_oi_ratio": cluster.get("max_vol_oi"),
            "new_position": cluster.get("new_position"),
            "dte": dte,
            "contracts": cluster.get("contracts"),
        },
    }


def recommend(
    rows: list[dict],
    bias_map: Optional[dict[str, str]] = None,
    *,
    min_vol_oi: float = 5.0,
    max_dte: int = 4,
    min_row_premium: float = 0.0,
    min_cluster_premium: float = 5_000_000.0,
    min_conviction: int = 1,
    require_confluence: bool = False,
) -> list[dict]:
    """
    Pure entry point: flow rows + per-ticker bias → ranked Recommendation Setups.

    Filters by vol/OI, short-dated DTE, then clusters and requires the cluster's
    total premium to clear ``min_cluster_premium``. Returns recommendations sorted
    by conviction (desc).
    """
    bias_map = bias_map or {}
    filtered = [
        r for r in rows
        if _passes_filters(r, min_vol_oi=min_vol_oi, max_dte=max_dte,
                           min_row_premium=min_row_premium)
    ]
    clusters = cluster_flow(filtered)

    recs: list[dict] = []
    for (ticker, _direction), cluster in clusters.items():
        if cluster["total_premium"] < min_cluster_premium:
            continue
        bias = bias_map.get(ticker)
        rec = build_recommendation(cluster, bias, premium_floor=min_cluster_premium)
        if rec["conviction_score"] < min_conviction:
            continue
        if require_confluence and rec["confluence"] != "confirmed":
            continue
        recs.append(rec)

    recs.sort(key=lambda x: x["conviction_score"], reverse=True)
    return recs


# ── async orchestrator (live wiring) ────────────────────────────────────────────
def _bias_from_signals(signals: list[dict]) -> dict[str, str]:
    """Map the most recent equity signal per ticker to a directional bias."""
    bias: dict[str, str] = {}
    for s in signals:                      # _recent_signals is newest-first
        t = s.get("ticker")
        if not t or t in bias:
            continue
        action = str(s.get("action", "")).upper()
        if action == "BUY":
            bias[t] = "BULLISH"
        elif action == "SELL":
            bias[t] = "BEARISH"
    return bias


async def generate_recommendations(   # pragma: no cover - live wiring/I/O
    *,
    min_vol_oi: float = 5.0,
    max_dte: int = 4,
    min_cluster_premium: float = 5_000_000.0,
    require_confluence: bool = False,
    top: int = 50,
) -> list[dict]:
    """
    Live recommendation feed: pull unusual options activity + recent Live Signals,
    cross-reference, and return structured Setup Recommendations.
    """
    from app.core.config import settings
    from app.services.unusual_activity import scan_unusual_activity

    rows = await scan_unusual_activity(settings.get_equity_watchlist())

    try:
        from app.api.routes.equity import _recent_signals
        bias_map = _bias_from_signals(list(_recent_signals))
    except Exception:
        bias_map = {}

    return recommend(
        rows, bias_map,
        min_vol_oi=min_vol_oi, max_dte=max_dte,
        min_cluster_premium=min_cluster_premium,
        require_confluence=require_confluence,
    )[:top]
