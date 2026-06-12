"""Backtest API routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid, json
from datetime import date

router = APIRouter()


class BacktestRunRequest(BaseModel):
    strategy: str
    start_date: str
    end_date: str
    starting_capital: float = 25000.0
    signal_score_override: float = 0.70


class BacktestCompareRequest(BaseModel):
    start_date: str
    end_date: str
    starting_capital: float = 25000.0


@router.post("/run")
async def run_backtest(req: BacktestRunRequest):
    """Kick off a backtest run. Returns run_id for polling results."""
    run_id = str(uuid.uuid4())
    # In production: enqueue to background task queue
    return {
        "run_id": run_id,
        "status": "queued",
        "strategy": req.strategy,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "message": "Backtest queued. Poll GET /api/backtest/{run_id}/results for status.",
    }


@router.get("/{run_id}/results")
async def get_backtest_results(run_id: str):
    """Get results for a completed backtest run."""
    return {
        "run_id": run_id,
        "status": "completed",
        "message": "Fetch from backtest_runs table by run_id",
    }


@router.get("/history")
async def get_backtest_history(limit: int = 20):
    """List recent backtest runs."""
    return {"runs": [], "total": 0}


@router.post("/compare")
async def compare_strategies(req: BacktestCompareRequest):
    """Run all 4 strategies on the same date range and return ranked results."""
    return {
        "status": "queued",
        "message": "Strategy comparison queued.",
        "start_date": req.start_date,
        "end_date": req.end_date,
    }
