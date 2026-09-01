"""
Name a broker-detected close for what it actually was.

The reconciler learns a position is gone and gets the execution price with it,
but has been stamping every such close `position_closed_at_broker` — true, and
useless. Nothing downstream could tell a stop-out from a target fill from a
position that vanished for some other reason, so no analysis of whether the
stop/target geometry works in production was possible at all.

This classifies only what the row can prove, and returns the neutral label
whenever it cannot. That asymmetry is the point: a wrong `stop_hit` is worse
than an honest `position_closed_at_broker`, because the whole reason this
exists is to make exit reasons trustworthy enough to measure. Every guard
below fails toward "I don't know".

Equity only. An options spread closes at a net debit that is not comparable
to a strike, and the bracket semantics differ — options exits keep the
neutral label rather than being force-fitted into this shape.
"""
from typing import Any, Optional

# Fills slip. A stop fills at or through its level, rarely better, so the
# tolerance is small and mostly absorbs rounding — a fill meaningfully
# better than the stop is not a stop fill and should not be labelled one.
TOLERANCE_PCT = 0.0025

UNKNOWN = "position_closed_at_broker"
STOP_HIT = "stop_hit"
TARGET_HIT = "target_hit"


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def classify_broker_exit(trade: Any, exit_price: Any) -> str:
    """
    Return STOP_HIT, TARGET_HIT, or UNKNOWN for a reconciler-detected close.

    Never raises — a classifier that can break the reconciliation loop would
    trade a reporting improvement for a position-tracking outage.
    """
    try:
        return _classify(trade, exit_price)
    except Exception:
        return UNKNOWN


def _classify(trade: Any, exit_price: Any) -> str:
    price = _f(exit_price)
    if price is None:
        return UNKNOWN

    spread_type = (getattr(trade, "spread_type", "") or "").lower()
    if spread_type not in ("equity_long", "equity_short"):
        return UNKNOWN

    entry = _f(getattr(trade, "credit_received", None))
    if entry is None:
        return UNKNOWN

    # The stop goes through equity_stop_distance(), which is what rejects the
    # reconciler-adopted `entry == stop` placeholder rows. Read literally
    # those would classify almost any exit as a stop-out.
    from app.services.portfolio_engine import equity_stop_distance

    stop = _f(getattr(trade, "long_strike", None))
    stop_is_real = stop is not None and equity_stop_distance(trade) is not None
    target = _f(getattr(trade, "target_price", None))

    is_short = spread_type == "equity_short"
    tol = TOLERANCE_PCT

    hit_stop = False
    hit_target = False

    if stop_is_real:
        hit_stop = (
            price >= stop * (1 - tol) if is_short else price <= stop * (1 + tol)
        )

    if target is not None:
        # A target on the wrong side of entry is a bad row, not a target.
        target_side_ok = target < entry if is_short else target > entry
        if target_side_ok:
            hit_target = (
                price <= target * (1 + tol)
                if is_short
                else price >= target * (1 - tol)
            )

    # Both would mean the levels cross or the fill is outside both — either
    # way the row cannot say which leg filled. Don't pick one.
    if hit_stop and hit_target:
        return UNKNOWN
    if hit_stop:
        return STOP_HIT
    if hit_target:
        return TARGET_HIT
    return UNKNOWN
