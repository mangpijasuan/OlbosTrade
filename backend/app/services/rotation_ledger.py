"""
Rotation-performance ledger — pure aggregation over closed rotation trades.

Reports honestly on the closed side of capital rotation only ("was closing
this position, by itself, a good or bad call in hindsight"). Deliberately
does NOT attempt to correlate a rotation close to the specific new position
it enabled — no structural link exists anywhere between a close and the
subsequent open it freed a slot for, and building one would need either a
new join-table-style link or a fragile timestamp-proximity heuristic. That
harder question is left open, not answered speculatively here.

No DB access in this module — see app/api/routes/portfolio.py's
GET /rotation-performance for the query that shapes rows into what
compute_rotation_ledger_stats() expects.
"""

from __future__ import annotations

# Matches analytics.py's embedded trades_sample cap — this ledger's "recent"
# list is embedded inside one aggregate response, not a standalone paginated
# dump route, so the smaller cap is the right precedent to follow.
RECENT_LIMIT = 20


def _pnl_stats(rows: list[dict]) -> dict:
    """Shared by the top-level result and each by_regime bucket."""
    total = len(rows)
    total_pnl = sum(r["pnl"] for r in rows)
    wins = [r for r in rows if r["pnl"] > 0]
    hold_days = [r["hold_days"] for r in rows if r.get("hold_days") is not None]
    return {
        "total": total,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / total, 2) if total else None,
        "win_rate": round(len(wins) / total, 3) if total else None,
        "avg_hold_days": round(sum(hold_days) / len(hold_days), 1) if hold_days else None,
    }


def compute_rotation_ledger_stats(rotations: list[dict]) -> dict:
    """
    rotations: list of dicts, each with at least ticker, pnl, regime,
    entry_date, exit_date, hold_days, exit_reason — shaped from
    exit_reason == "position_rotation" Trade rows (rows with pnl is None
    already excluded by the caller, matching analytics.py's own convention
    of never counting an unknown P&L as a fabricated flat trade).
    """
    stats = _pnl_stats(rotations)

    regimes = sorted({r.get("regime") for r in rotations if r.get("regime")})
    by_regime = {r: _pnl_stats([row for row in rotations if row.get("regime") == r]) for r in regimes}

    recent = sorted(rotations, key=lambda r: r.get("exit_date") or "", reverse=True)[:RECENT_LIMIT]

    return {**stats, "by_regime": by_regime, "recent": recent}
