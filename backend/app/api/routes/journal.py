"""Journal routes."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class JournalEntryIn(BaseModel):
    trade_id: Optional[str] = None
    pre_trade_thesis: str
    confidence_level: int
    market_context: str


class JournalEntryPatch(BaseModel):
    post_trade_notes: Optional[str] = None
    followed_rules: Optional[bool] = None
    exit_felt_right: Optional[bool] = None
    tags: Optional[list[str]] = None
    loss_category: Optional[str] = None
    mistake_tags: Optional[list[str]] = None


@router.post("/entry")
async def create_entry(entry: JournalEntryIn):
    return {"created": True, "entry": entry.model_dump()}

@router.get("/entries")
async def list_entries(limit: int = 50, offset: int = 0):
    return {"entries": [], "total": 0}

@router.get("/{trade_id}")
async def get_entry_by_trade(trade_id: str):
    return {"trade_id": trade_id, "entry": None}

@router.put("/{entry_id}")
async def update_entry(entry_id: str, patch: JournalEntryPatch):
    return {"updated": True, "entry_id": entry_id}

@router.get("/analytics/tags")
async def get_tag_performance():
    return {"tag_performance": []}

@router.get("/analytics/mistakes")
async def get_mistake_frequency():
    return {"mistakes": {}}

@router.get("/analytics/rule-breach-impact")
async def get_rule_breach_impact():
    return {"impact": None, "message": "Needs journal entries with followed_rules data"}

@router.get("/review/monthly/{month}")
async def get_monthly_review(month: str):
    return {"month": month, "review": None}
