"""
Pre-rotation safety checklist.

Thirteen checks that must all pass before Capital Rotation is allowed to close
anything. Read-only: it inspects, asserts and reports, and never places,
cancels or modifies an order.

Two principles shape it.

**Behavioural assertions beat config reads.** "Winner Protection healthy" does
not mean `position_rotation_winner_pnl_floor` is set; it means a synthetic
profitable candidate is actually rejected by the live ranking code, right now.
Same for the approval boundary: the check calls the real close function with
no token and requires it to raise. A config read tells you what someone
intended; an assertion tells you what the code does.

**Unknown is a failure, not a pass.** Every check returns pass / fail /
unknown, and `all_clear` requires every check to be an outright pass. A check
that could not determine its answer blocks rotation, because the cost of a
wrong "proceed" is a real position closed and a real order sent.

Two checks are expected to fail today, and that is the point of writing them:
the account-push subscription never establishes (the subscribe wedge), and
IBKR has dropped the parent linkage on every resting order. Neither is fixed
by this module; both are surfaced so they cannot be stepped over silently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"

# How stale account pushes may be before "account state synchronized" fails.
# The cache short-circuit keeps reads working far longer than this; the check
# is deliberately stricter than the read path, because a working read off a
# stale cache is exactly the condition that hid the 08-27 equity blackout.
ACCOUNT_PUSH_MAX_AGE_S = 600.0


def _check(name: str, status: str, detail: str, **extra) -> dict:
    return {"check": name, "status": status, "detail": detail, **extra}


async def _ibkr_connection(broker: Any) -> dict:
    try:
        ib = getattr(broker, "ib", None)
        connected = bool(getattr(broker, "_connected", False))
        live = bool(ib.isConnected()) if ib is not None else None
        if live is None:
            return _check("ibkr_connection", UNKNOWN,
                          f"{type(broker).__name__} exposes no ib client")
        if connected and live:
            return _check("ibkr_connection", PASS, "connected")
        return _check("ibkr_connection", FAIL,
                      f"_connected={connected} isConnected={live}")
    except Exception as exc:
        return _check("ibkr_connection", UNKNOWN, f"{type(exc).__name__}: {exc}")


async def _account_state(broker: Any) -> dict:
    """Fails when account pushes are not flowing, even though reads still work
    off the cache. See the module docstring."""
    try:
        summary = await broker.get_account_summary()
        age = getattr(summary, "data_age_seconds", None)
        stale = getattr(summary, "is_stale", None)
        if age is None:
            return _check("account_state_synchronized", UNKNOWN,
                          "broker reports no push age")
        if stale or age > ACCOUNT_PUSH_MAX_AGE_S:
            return _check("account_state_synchronized", FAIL,
                          f"last account push {age:.0f}s ago "
                          f"(limit {ACCOUNT_PUSH_MAX_AGE_S:.0f}s) — reads are "
                          "being served from cache, not a live subscription",
                          age_seconds=age)
        return _check("account_state_synchronized", PASS,
                      f"last push {age:.0f}s ago", age_seconds=age)
    except Exception as exc:
        return _check("account_state_synchronized", UNKNOWN, f"{type(exc).__name__}: {exc}")


async def _positions_synchronized(broker: Any) -> dict:
    """DB open trades must agree with the broker on symbol and quantity."""
    try:
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade

        async with AsyncSessionLocal() as session:
            open_trades = (await session.execute(
                select(Trade).where(Trade.status == "open")
            )).scalars().all()

        live: dict[str, float] = {}
        for p in await broker.get_positions():
            sym = (getattr(p, "symbol", "") or "").upper()
            q = getattr(p, "quantity", None)
            if sym and q is not None:
                live[sym] = live.get(sym, 0.0) + abs(float(q))

        db: dict[str, float] = {}
        for t in open_trades:
            sym = (t.underlying or "").upper()
            db[sym] = db.get(sym, 0.0) + abs(float(t.quantity or 0))

        mismatches = [
            {"symbol": s, "db": db.get(s), "broker": live.get(s)}
            for s in sorted(set(db) | set(live))
            if abs((db.get(s) or 0) - (live.get(s) or 0)) > 0.01
        ]
        if mismatches:
            return _check("positions_synchronized", FAIL,
                          f"{len(mismatches)} symbol(s) disagree between DB and broker",
                          mismatches=mismatches)
        return _check("positions_synchronized", PASS,
                      f"{len(db)} position(s) agree", symbols=sorted(db))
    except Exception as exc:
        return _check("positions_synchronized", UNKNOWN, f"{type(exc).__name__}: {exc}")


async def _order_book(broker: Any) -> tuple[dict, list[dict]]:
    """Shared read for the three order checks — one refresh, not three."""
    result = await broker.get_open_orders(refresh=True)
    return result, result.get("orders", [])


def _orders_synchronized(result: dict) -> dict:
    source = result.get("source")
    if source == "refreshed":
        return _check("open_orders_synchronized", PASS,
                      f"{len(result.get('orders', []))} order(s) read live from IBKR")
    return _check("open_orders_synchronized", FAIL,
                  f"order book came from '{source}' — a cache fall-back means "
                  "an empty or partial list cannot be trusted")


def _no_orphans(orders: list[dict], held: set[str]) -> dict:
    orphans: dict[str, int] = {}
    for o in orders:
        sym = (o.get("symbol") or "").upper()
        if sym and sym not in held:
            orphans[sym] = orphans.get(sym, 0) + 1
    if orphans:
        total = sum(orphans.values())
        return _check("no_orphan_orders", FAIL,
                      f"{total} order(s) on {len(orphans)} symbol(s) with no position",
                      orphans=orphans)
    return _check("no_orphan_orders", PASS, "every resting order maps to a position")


def _no_duplicates(orders: list[dict]) -> dict:
    """Two live orders identical in symbol/side/type/qty/price are almost
    certainly a double-submit, and would double the intended exposure."""
    seen: dict[tuple, list] = {}
    for o in orders:
        key = (
            (o.get("symbol") or "").upper(), o.get("action"), o.get("order_type"),
            o.get("remaining"), o.get("stop_price"), o.get("limit_price"),
        )
        seen.setdefault(key, []).append(o.get("order_id"))
    dupes = {str(k): v for k, v in seen.items() if len(v) > 1}
    if dupes:
        return _check("no_duplicate_orders", FAIL,
                      f"{len(dupes)} duplicate order group(s)", duplicates=dupes)
    return _check("no_duplicate_orders", PASS, "no identical order pairs")


def _brackets_consistent(orders: list[dict], held: set[str]) -> dict:
    """Every protective order should either still carry its parent link, or
    belong to a held position. An unparented protective order on a symbol we
    hold nothing in is a standalone stop that will open a position if touched,
    with no sibling to cancel it."""
    unparented = [
        o.get("order_id") for o in orders
        if o.get("is_protective")
        and not o.get("parent_id")
        and (o.get("symbol") or "").upper() not in held
    ]
    orphan_linked = [
        o.get("order_id") for o in orders
        if not o.get("parent_id") and (o.get("symbol") or "").upper() in held
    ]
    if unparented:
        return _check("brackets_consistent", FAIL,
                      f"{len(unparented)} protective order(s) with no parent link "
                      "and no position — standalone stops, nothing OCA-cancels a sibling",
                      order_ids=unparented)
    if orphan_linked:
        # Held positions whose orders lost their parent link still protect a
        # real position, so this is a warning shape, not a blocker — but it is
        # reported rather than hidden.
        return _check("brackets_consistent", PASS,
                      f"all protective orders map to positions; note "
                      f"{len(orphan_linked)} have lost their IBKR parent link",
                      lost_parent_link=orphan_linked)
    return _check("brackets_consistent", PASS, "parent links intact")


async def _risk_engine() -> dict:
    """Runs the real GuardrailEngine against the real portfolio state.

    There is no module-level `guardrails` singleton — the engine is a class
    instantiated per use (main.py builds its own `_guardrail_engine`), and
    check_all() takes the portfolio state rather than fetching it.
    """
    try:
        from app.api.routes.trade_desk import _fetch_portfolio_state
        from app.services.guardrails import GuardrailEngine

        portfolio = await _fetch_portfolio_state()
        state = GuardrailEngine().check_all(portfolio)
        allowed = getattr(state, "trading_allowed", None)
        if allowed is None:
            return _check("risk_engine_healthy", UNKNOWN, "guardrails returned no verdict")
        return _check("risk_engine_healthy", PASS if allowed else FAIL,
                      f"trading_allowed={allowed}"
                      + (f" reason={getattr(state, 'reason', None)}" if not allowed else ""))
    except Exception as exc:
        return _check("risk_engine_healthy", UNKNOWN, f"{type(exc).__name__}: {exc}")


def _winner_protection() -> dict:
    """Behavioural: a synthetic profitable candidate must be rejected by the
    real ranking code. Also asserts the fail-closed path — an unknown-P&L
    candidate must not be selectable either."""
    try:
        from app.services.position_rotation import RotationCandidate, select_rotation_targets

        def c(name, pnl):
            return RotationCandidate(
                trade_id=name, underlying=name, unrealized_pnl=pnl,
                confidence=0.1, entry_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                spread_type="equity_long", quality_score=1.0,
            )

        winner_picked = select_rotation_targets(
            [c("WINNER", 5000.0), c("ALSO_UP", 10.0)],
            incoming_ticker="X", count=1)
        unknown_picked = select_rotation_targets(
            [c("NOPNL", None), c("ALSO_NONE", None)],
            incoming_ticker="X", count=1)

        if winner_picked:
            return _check("winner_protection_healthy", FAIL,
                          f"a profitable position was selectable: {winner_picked[0].underlying}")
        if unknown_picked:
            return _check("winner_protection_healthy", FAIL,
                          "a candidate with unknown P&L was selectable")
        return _check("winner_protection_healthy", PASS,
                      "profitable and unknown-P&L candidates both rejected by live ranking")
    except Exception as exc:
        return _check("winner_protection_healthy", UNKNOWN, f"{type(exc).__name__}: {exc}")


async def _capital_rotation(broker: Any) -> dict:
    try:
        from app.core.config import settings
        from app.services.position_rotation import build_rotation_candidates

        candidates = await build_rotation_candidates(broker)
        return _check("capital_rotation_healthy", PASS,
                      f"candidate builder returned {len(candidates)} candidate(s)",
                      armed=bool(getattr(settings, "position_rotation_on_max", False)),
                      candidates=[c.underlying for c in candidates])
    except Exception as exc:
        return _check("capital_rotation_healthy", UNKNOWN, f"{type(exc).__name__}: {exc}")


async def _approval_boundary() -> dict:
    """Behavioural: the real close function must refuse a rotation-sourced
    close carrying no approval token. A mock broker is passed so that a
    regression here fails the check rather than sending an order."""
    try:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        from app.services.position_rotation import (
            ROTATION_CLOSED_BY, RotationApprovalRequired, close_equity_trade,
        )

        probe = MagicMock()
        probe.cancel_open_orders = AsyncMock(return_value=0)
        probe.place_equity_order = AsyncMock()
        probe.get_equity_positions = AsyncMock(
            return_value=[SimpleNamespace(symbol="PROBE", quantity=1)])
        trade = SimpleNamespace(id="preflight-probe", underlying="PROBE", quantity=1,
                                spread_type="equity_long", credit_received=1.0,
                                strategy="equity")
        try:
            await close_equity_trade(trade, broker=probe, closed_by=ROTATION_CLOSED_BY)
        except RotationApprovalRequired:
            if probe.place_equity_order.called:
                return _check("approval_boundary_healthy", FAIL,
                              "guard raised but an order was already submitted")
            return _check("approval_boundary_healthy", PASS,
                          "unapproved rotation close refused before any broker call")
        return _check("approval_boundary_healthy", FAIL,
                      "unapproved rotation close was NOT refused")
    except Exception as exc:
        return _check("approval_boundary_healthy", UNKNOWN, f"{type(exc).__name__}: {exc}")


def _kill_switch() -> dict:
    """Readable and reporting a definite state. Deliberately does not engage
    it — testing by tripping would halt the desk."""
    try:
        from app.api.routes.trade_desk import _is_kill_switch_active
        engaged = bool(_is_kill_switch_active())
        if engaged:
            return _check("kill_switch_functional", FAIL,
                          "kill switch is ENGAGED — no orders may be sent")
        return _check("kill_switch_functional", PASS, "readable, not engaged")
    except Exception as exc:
        return _check("kill_switch_functional", UNKNOWN, f"{type(exc).__name__}: {exc}")


async def _audit_logging() -> dict:
    """Can the execution_events table actually be read? A write probe is not
    performed — polluting the audit trail to prove the audit trail works is a
    poor trade."""
    try:
        from sqlalchemy import select, func
        from app.core.database import AsyncSessionLocal
        from app.models.execution_event import ExecutionEvent

        async with AsyncSessionLocal() as session:
            n = (await session.execute(
                select(func.count()).select_from(ExecutionEvent)
            )).scalar()
        return _check("audit_logging_functional", PASS,
                      f"execution_events readable ({n} row(s))")
    except Exception as exc:
        return _check("audit_logging_functional", UNKNOWN, f"{type(exc).__name__}: {exc}")


async def run_preflight(broker: Any) -> dict:
    """All thirteen checks. Read-only. `all_clear` requires every check to
    PASS — an unknown blocks, deliberately."""
    checks: list[dict] = []
    checks.append(await _ibkr_connection(broker))
    checks.append(await _account_state(broker))
    checks.append(await _positions_synchronized(broker))

    held: set[str] = set()
    try:
        for p in await broker.get_positions():
            sym = (getattr(p, "symbol", "") or "").upper()
            if sym:
                held.add(sym)
    except Exception:
        pass

    try:
        result, orders = await _order_book(broker)
        checks.append(_orders_synchronized(result))
        checks.append(_no_orphans(orders, held))
        checks.append(_no_duplicates(orders))
        checks.append(_brackets_consistent(orders, held))
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        for name in ("open_orders_synchronized", "no_orphan_orders",
                     "no_duplicate_orders", "brackets_consistent"):
            checks.append(_check(name, UNKNOWN, msg))

    checks.append(await _risk_engine())
    checks.append(_winner_protection())
    checks.append(await _capital_rotation(broker))
    checks.append(await _approval_boundary())
    checks.append(_kill_switch())
    checks.append(await _audit_logging())

    failed = [c["check"] for c in checks if c["status"] == FAIL]
    unknown = [c["check"] for c in checks if c["status"] == UNKNOWN]
    return {
        "all_clear": not failed and not unknown,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "passed": len(checks) - len(failed) - len(unknown),
        "total": len(checks),
        "failed": failed,
        "unknown": unknown,
        "checks": checks,
    }
