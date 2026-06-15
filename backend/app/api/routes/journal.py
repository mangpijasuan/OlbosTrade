"""
Journal routes — CRUD wired to journal_entries DB table + analytics via JournalAnalytics.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.models.journal_entry import JournalEntry
from app.models.trade import Trade
from app.services.journal_service import JournalAnalytics, JournalEntryOut

router = APIRouter()
_analytics = JournalAnalytics()


def _to_out(e: JournalEntry, trade: Optional[Trade] = None) -> JournalEntryOut:
    return JournalEntryOut(
        id=str(e.id),
        trade_id=str(e.trade_id) if e.trade_id else None,
        strategy=trade.strategy if trade else None,
        underlying=trade.underlying if trade else None,
        pre_trade_thesis=e.pre_trade_thesis or "",
        confidence_level=e.confidence_level or 3,
        market_context=e.market_context or "",
        post_trade_notes=e.post_trade_notes,
        followed_rules=e.followed_rules,
        exit_felt_right=e.exit_felt_right,
        tags=e.tags or [],
        loss_category=e.loss_category,
        mistake_tags=e.mistake_tags or [],
        pnl=float(trade.pnl) if (trade and trade.pnl is not None) else None,
        signal_score=float(trade.signal_score) if (trade and trade.signal_score) else None,
        entry_date=e.created_at.date() if e.created_at else date.today(),
        exit_date=trade.exit_date.date() if (trade and trade.exit_date) else None,
    )


async def _load_all() -> list[JournalEntryOut]:
    async with AsyncSessionLocal() as session:
        entries = (await session.execute(
            select(JournalEntry).order_by(JournalEntry.created_at.desc())
        )).scalars().all()
        trade_ids = [e.trade_id for e in entries if e.trade_id]
        trade_map: dict = {}
        if trade_ids:
            rows = (await session.execute(select(Trade).where(Trade.id.in_(trade_ids)))).scalars().all()
            trade_map = {t.id: t for t in rows}
    return [_to_out(e, trade_map.get(e.trade_id)) for e in entries]


class JournalEntryIn(BaseModel):
    trade_id:         Optional[str] = None
    pre_trade_thesis: str
    confidence_level: int
    market_context:   str

class JournalEntryPatch(BaseModel):
    post_trade_notes: Optional[str]       = None
    followed_rules:   Optional[bool]      = None
    exit_felt_right:  Optional[bool]      = None
    tags:             Optional[list[str]] = None
    loss_category:    Optional[str]       = None
    mistake_tags:     Optional[list[str]] = None


@router.post("/entry", status_code=201)
async def create_entry(entry: JournalEntryIn):
    trade_uuid = None
    if entry.trade_id:
        try:
            trade_uuid = uuid.UUID(entry.trade_id)
        except ValueError:
            raise HTTPException(400, "Invalid trade_id UUID")
    row = JournalEntry(
        id=uuid.uuid4(), trade_id=trade_uuid,
        pre_trade_thesis=entry.pre_trade_thesis,
        confidence_level=max(1, min(5, entry.confidence_level)),
        market_context=entry.market_context,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return {"created": True, "id": str(row.id)}


@router.get("/entries")
async def list_entries(limit: int = Query(50, le=500), offset: int = Query(0)):
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(JournalEntry).order_by(JournalEntry.created_at.desc()).offset(offset).limit(limit)
            )).scalars().all()
            total = (await session.execute(select(func.count(JournalEntry.id)))).scalar() or 0
            trade_ids = [r.trade_id for r in rows if r.trade_id]
            trade_map: dict = {}
            if trade_ids:
                trades = (await session.execute(select(Trade).where(Trade.id.in_(trade_ids)))).scalars().all()
                trade_map = {t.id: t for t in trades}
        return {"entries": [_to_out(r, trade_map.get(r.trade_id)).__dict__ for r in rows], "total": total}
    except Exception as exc:
        return {"entries": [], "total": 0, "error": str(exc)}


@router.get("/analytics/tags")
async def get_tag_performance():
    entries = await _load_all()
    if not entries:
        return {"tag_performance": [], "message": "No journal entries yet."}
    return {"tag_performance": [p.__dict__ for p in _analytics.tag_performance(entries)]}


@router.get("/analytics/mistakes")
async def get_mistake_frequency():
    entries = await _load_all()
    if not entries:
        return {"mistakes": {}, "message": "No journal entries yet."}
    return {"mistakes": _analytics.mistake_frequency(entries)}


@router.get("/analytics/rule-breach-impact")
async def get_rule_breach_impact():
    entries = await _load_all()
    if not [e for e in entries if e.followed_rules is not None]:
        return {"impact": None, "message": "No entries with followed_rules data yet."}
    return {"impact": _analytics.rule_breach_impact(entries).__dict__}


@router.get("/review/monthly/{month}")
async def get_monthly_review(month: str):
    entries = await _load_all()
    return {"month": month, "review": _analytics.generate_monthly_review(entries, month).__dict__}


@router.get("/{entry_id}")
async def get_entry(entry_id: str):
    try:
        uid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    async with AsyncSessionLocal() as session:
        row = await session.get(JournalEntry, uid)
        if not row:
            result = await session.execute(select(JournalEntry).where(JournalEntry.trade_id == uid))
            row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(404, "Journal entry not found")
        trade = await session.get(Trade, row.trade_id) if row.trade_id else None
    return {"entry": _to_out(row, trade).__dict__}


@router.put("/{entry_id}")
async def update_entry(entry_id: str, patch: JournalEntryPatch):
    try:
        uid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    async with AsyncSessionLocal() as session:
        row = await session.get(JournalEntry, uid)
        if not row:
            raise HTTPException(404, "Journal entry not found")
        if patch.post_trade_notes is not None: row.post_trade_notes = patch.post_trade_notes
        if patch.followed_rules   is not None: row.followed_rules   = patch.followed_rules
        if patch.exit_felt_right  is not None: row.exit_felt_right  = patch.exit_felt_right
        if patch.tags             is not None: row.tags             = patch.tags
        if patch.loss_category    is not None: row.loss_category    = patch.loss_category
        if patch.mistake_tags     is not None: row.mistake_tags     = patch.mistake_tags
        await session.commit()
        await session.refresh(row)
        trade = await session.get(Trade, row.trade_id) if row.trade_id else None
    return {"updated": True, "entry": _to_out(row, trade).__dict__}
