"""
Alert + Notification service.

Rule CRUD, notification store, and rule evaluation with cooldown-based
deduplication. When a rule fires it creates a NOTIFICATION (and, for
copilot/autopilot, an outcome that is explicitly marked as requiring the full
downstream gate check). It never creates an order.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.alert import AlertRule, Notification
from app.services.alerts.rule_engine import Predicate, Rule, route_outcome
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Notifications ────────────────────────────────────────────────────────────
async def create_notification(*, kind: str, title: str, body: str = "",
                              symbol: str | None = None, severity: str = "info",
                              rule_id=None) -> dict:
    async with AsyncSessionLocal() as session:
        n = Notification(kind=kind, title=title, body=body, symbol=symbol,
                         severity=severity, rule_id=rule_id)
        session.add(n)
        await session.commit()
        await session.refresh(n)
        return _notif(n)


async def list_notifications(limit: int = 50, unread_only: bool = False) -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
        if unread_only:
            stmt = stmt.where(Notification.read.is_(False))
        rows = (await session.execute(stmt)).scalars().all()
        return [_notif(n) for n in rows]


async def unread_count() -> int:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Notification.id).where(Notification.read.is_(False))
        )).scalars().all()
        return len(rows)


async def mark_read(notification_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        await session.execute(update(Notification).where(Notification.id == notification_id).values(read=True))
        await session.commit()
        return True


async def mark_all_read() -> int:
    async with AsyncSessionLocal() as session:
        res = await session.execute(update(Notification).where(Notification.read.is_(False)).values(read=True))
        await session.commit()
        return res.rowcount or 0


# ── Alert rules ──────────────────────────────────────────────────────────────
async def list_rules() -> list[dict]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(AlertRule).order_by(AlertRule.created_at.desc()))).scalars().all()
        return [_rule(r) for r in rows]


async def create_rule(*, name: str, symbol: str, predicates: list[dict],
                      mode: str = "manual", cooldown_min: int = 60) -> dict:
    async with AsyncSessionLocal() as session:
        r = AlertRule(name=name, symbol=symbol.upper(), predicates=predicates,
                      mode=mode, cooldown_min=cooldown_min)
        session.add(r)
        await session.commit()
        await session.refresh(r)
        return _rule(r)


async def toggle_rule(rule_id: str, enabled: bool) -> bool:
    async with AsyncSessionLocal() as session:
        await session.execute(update(AlertRule).where(AlertRule.id == rule_id).values(enabled=enabled))
        await session.commit()
        return True


async def delete_rule(rule_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        r = (await session.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalars().first()
        if not r:
            return False
        await session.delete(r)
        await session.commit()
        return True


# ── Evaluation ───────────────────────────────────────────────────────────────
async def evaluate_symbol(symbol: str, snapshot: dict) -> list[dict]:
    """Evaluate all enabled rules for a symbol against a metrics snapshot.

    Respects each rule's cooldown (dedup). Fires create notifications only —
    never orders. Returns the outcomes produced."""
    sym = symbol.upper()
    now = datetime.now(timezone.utc)
    produced: list[dict] = []

    async with AsyncSessionLocal() as session:
        rules = (await session.execute(
            select(AlertRule).where(AlertRule.symbol == sym, AlertRule.enabled.is_(True))
        )).scalars().all()

        for r in rules:
            # Cooldown dedup.
            if r.last_fired_at and (now - r.last_fired_at) < timedelta(minutes=r.cooldown_min):
                continue
            rule = Rule(
                rule_id=str(r.id), name=r.name, symbol=r.symbol, mode=r.mode,
                predicates=[Predicate(p["metric"], p["op"], p.get("value")) for p in r.predicates],
            )
            if not rule.matches(snapshot):
                continue
            evidence = [f"{p.metric} {p.op} {p.value}" for p in rule.predicates]
            outcome = route_outcome(rule, snapshot, evidence)
            r.last_fired_at = now
            session.add(Notification(
                kind="alert", symbol=sym, title=outcome.message,
                body=" · ".join(evidence),
                severity="warning" if outcome.kind != "notify" else "info",
                rule_id=r.id,
            ))
            produced.append(outcome.to_dict())
        if produced:
            await session.commit()
    return produced


def _notif(n: Notification) -> dict:
    return {
        "id": str(n.id), "kind": n.kind, "symbol": n.symbol, "title": n.title,
        "body": n.body, "severity": n.severity, "read": n.read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _rule(r: AlertRule) -> dict:
    return {
        "id": str(r.id), "name": r.name, "symbol": r.symbol, "predicates": r.predicates,
        "mode": r.mode, "enabled": r.enabled, "cooldown_min": r.cooldown_min,
        "last_fired_at": r.last_fired_at.isoformat() if r.last_fired_at else None,
    }
