"""
Quant Research & Strategy Lab — API routes (Phase 1).

Endpoints
---------
POST   /api/quant/strategies                  create strategy
GET    /api/quant/strategies                  list strategies
GET    /api/quant/strategies/{id}             fetch strategy (latest version)
PUT    /api/quant/strategies/{id}             update strategy (bumps version)
GET    /api/quant/strategies/{id}/versions    list all versions
POST   /api/quant/backtest                    run backtest (async)
GET    /api/quant/backtest/{backtest_id}      get backtest result
GET    /api/quant/backtest/{backtest_id}/export  export trade log as JSON
GET    /api/quant/backtest/history            recent backtest runs
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from app.core.database import AsyncSessionLocal
from app.models.quant_models import QuantStrategy, QuantStrategyVersion, QuantBacktestRun
from app.services.quant_research import BacktestEngine, StrategyBuilder, StrategyConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# In-memory cache for active backtest runs (fast polling during execution).
# Capped at 200 entries — oldest evicted first once the limit is reached.
_bt_runs: dict[str, dict] = {}
_BT_RUNS_MAX = 200


def _bt_runs_set(run_id: str, data: dict) -> None:
    """Insert/update _bt_runs, evicting the oldest entry when the cap is exceeded."""
    _bt_runs[run_id] = data
    if len(_bt_runs) > _BT_RUNS_MAX:
        oldest_key = next(iter(_bt_runs))
        del _bt_runs[oldest_key]


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class StrategyCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    direction: str = "LONG"
    entry: list[dict] = Field(default_factory=list)
    entry_logic: str = "AND"
    filter: list[dict] = Field(default_factory=list)
    filter_logic: str = "AND"
    confirmation: list[dict] = Field(default_factory=list)
    confirmation_logic: str = "AND"
    regime: str = "ANY"
    stop_atr_mult: float = 1.5
    target_atr_mult: float = 3.0
    position_size_pct: float = 2.0
    exit: list[dict] = Field(default_factory=list)
    exit_logic: str = "OR"
    trading_hours_start: str = "09:30"
    trading_hours_end: str = "16:00"
    max_concurrent_positions: int = 5
    commission_per_share: float = 0.005
    spread_pct: float = 0.001
    slippage_pct: float = 0.001
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 15.0


class BacktestRequest(BaseModel):
    strategy_id: Optional[str] = None
    # Inline strategy config (used when strategy_id is not provided)
    strategy_config: Optional[dict] = None

    symbol: str = "SPY"
    start_date: str = "2022-01-01"
    end_date: str = "2024-12-31"
    timeframe: str = "1d"
    starting_capital: float = 100_000.0

    # Execution assumption overrides (optional — defaults come from strategy_config)
    commission_per_share: Optional[float] = None
    spread_pct: Optional[float] = None
    slippage_pct: Optional[float] = None


# ── Strategy CRUD ─────────────────────────────────────────────────────────────

@router.post("/strategies")
async def create_strategy(req: StrategyCreateRequest):
    """Create a new strategy and save version 1."""
    try:
        cfg = StrategyBuilder.build(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    strategy_id = uuid.uuid4()
    config_dict = cfg.to_dict()

    async with AsyncSessionLocal() as session:
        strat = QuantStrategy(
            id=strategy_id,
            name=cfg.name,
            description=req.description,
            current_version=1,
            config=config_dict,
        )
        version = QuantStrategyVersion(
            strategy_id=strategy_id,
            version=1,
            name=cfg.name,
            config=config_dict,
        )
        session.add(strat)
        session.add(version)
        await session.commit()

    return {
        "strategy_id": str(strategy_id),
        "version":     1,
        "name":        cfg.name,
        "config":      config_dict,
    }


@router.get("/strategies")
async def list_strategies(limit: int = 50):
    """List all active strategies."""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(QuantStrategy)
            .where(QuantStrategy.is_active == True)
            .order_by(desc(QuantStrategy.updated_at))
            .limit(limit)
        )).scalars().all()

    return {
        "strategies": [
            {
                "strategy_id":     str(r.id),
                "name":            r.name,
                "description":     r.description,
                "current_version": r.current_version,
                "config":          r.config,
                "created_at":      r.created_at.isoformat() if r.created_at else None,
                "updated_at":      r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str):
    """Fetch a strategy by ID (returns the latest version config)."""
    try:
        sid = uuid.UUID(strategy_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid strategy_id format")

    async with AsyncSessionLocal() as session:
        row = await session.get(QuantStrategy, sid)
        if not row:
            raise HTTPException(status_code=404, detail="Strategy not found")

    return {
        "strategy_id":     str(row.id),
        "name":            row.name,
        "description":     row.description,
        "current_version": row.current_version,
        "config":          row.config,
        "created_at":      row.created_at.isoformat() if row.created_at else None,
        "updated_at":      row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/strategies/{strategy_id}")
async def update_strategy(strategy_id: str, req: StrategyCreateRequest):
    """Update a strategy — creates a new immutable version snapshot."""
    try:
        sid = uuid.UUID(strategy_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid strategy_id format")

    try:
        cfg = StrategyBuilder.build(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    config_dict = cfg.to_dict()

    async with AsyncSessionLocal() as session:
        row = await session.get(QuantStrategy, sid)
        if not row:
            raise HTTPException(status_code=404, detail="Strategy not found")

        new_version = row.current_version + 1
        row.name            = cfg.name
        row.description     = req.description
        row.current_version = new_version
        row.config          = config_dict

        version = QuantStrategyVersion(
            strategy_id=sid,
            version=new_version,
            name=cfg.name,
            config=config_dict,
        )
        session.add(version)
        await session.commit()

    return {
        "strategy_id": strategy_id,
        "version":     new_version,
        "name":        cfg.name,
        "config":      config_dict,
    }


@router.get("/strategies/{strategy_id}/versions")
async def list_strategy_versions(strategy_id: str):
    """List all immutable versions of a strategy."""
    try:
        sid = uuid.UUID(strategy_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid strategy_id format")

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(QuantStrategyVersion)
            .where(QuantStrategyVersion.strategy_id == sid)
            .order_by(QuantStrategyVersion.version)
        )).scalars().all()

    return {
        "strategy_id": strategy_id,
        "versions": [
            {
                "version":    r.version,
                "name":       r.name,
                "config":     r.config,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ── Backtest ──────────────────────────────────────────────────────────────────

async def _run_backtest_task(run_id: str, req: BacktestRequest) -> None:
    """Background task: execute backtest and update the DB record."""
    _bt_runs[run_id]["status"] = "running"
    try:
        # Resolve strategy config
        if req.strategy_id:
            try:
                sid = uuid.UUID(req.strategy_id)
            except ValueError:
                raise ValueError(f"Invalid strategy_id: {req.strategy_id}")
            async with AsyncSessionLocal() as session:
                strat_row = await session.get(QuantStrategy, sid)
            if not strat_row:
                raise ValueError(f"Strategy {req.strategy_id} not found")
            config_dict = dict(strat_row.config)
            strategy_version = strat_row.current_version
        elif req.strategy_config:
            config_dict = req.strategy_config
            strategy_version = None
        else:
            raise ValueError("Either strategy_id or strategy_config must be provided")

        # Allow per-request cost overrides
        if req.commission_per_share is not None:
            config_dict["commission_per_share"] = req.commission_per_share
        if req.spread_pct is not None:
            config_dict["spread_pct"] = req.spread_pct
        if req.slippage_pct is not None:
            config_dict["slippage_pct"] = req.slippage_pct

        cfg = StrategyBuilder.build(config_dict)

        engine = BacktestEngine()
        result = await asyncio.to_thread(
            engine.run,
            cfg,
            req.symbol,
            req.start_date,
            req.end_date,
            req.starting_capital,
            req.timeframe,
        )

        completed_at = datetime.now(timezone.utc)

        _bt_runs[run_id].update({
            "status":          "completed",
            "completed_at":    completed_at.isoformat(),
            "symbol":          result.symbol,
            "start_date":      str(result.start_date),
            "end_date":        str(result.end_date),
            "starting_capital": result.starting_capital,
            **result.metrics,
            "equity_curve":    result.equity_curve[:500],  # cap for API response size
            "drawdown_curve":  result.drawdown_curve[:500],
            "monthly_returns": result.monthly_returns,
            "trades":          result.trades,
        })

        # Persist to DB
        try:
            async with AsyncSessionLocal() as session:
                bt_row = await session.get(QuantBacktestRun, uuid.UUID(run_id))
                if bt_row:
                    bt_row.status        = "completed"
                    bt_row.completed_at  = completed_at
                    bt_row.metrics       = result.metrics
                    bt_row.equity_curve  = result.equity_curve
                    bt_row.trades        = result.trades
                    if req.strategy_id:
                        bt_row.strategy_version = strategy_version
                    await session.commit()
        except Exception as db_exc:
            logger.warning("Failed to persist quant backtest %s: %s", run_id, db_exc)

    except Exception as exc:
        logger.exception("Backtest %s failed", run_id)
        _bt_runs[run_id].update({"status": "failed", "error": str(exc)})
        try:
            async with AsyncSessionLocal() as session:
                bt_row = await session.get(QuantBacktestRun, uuid.UUID(run_id))
                if bt_row:
                    bt_row.status = "failed"
                    bt_row.error  = str(exc)
                    await session.commit()
        except Exception:
            pass


@router.post("/backtest")
async def run_backtest(req: BacktestRequest):
    """Kick off a quant backtest. Poll GET /api/quant/backtest/{id} for status."""
    if not req.strategy_id and not req.strategy_config:
        raise HTTPException(status_code=422, detail="Either strategy_id or strategy_config is required")

    run_id = str(uuid.uuid4())
    sid_uuid = uuid.UUID(req.strategy_id) if req.strategy_id else None

    # Persist queued record immediately
    parameters = {
        "timeframe":            req.timeframe,
        "commission_per_share": req.commission_per_share,
        "spread_pct":           req.spread_pct,
        "slippage_pct":         req.slippage_pct,
    }
    strategy_snapshot = req.strategy_config or {}
    if not strategy_snapshot and req.strategy_id:
        try:
            async with AsyncSessionLocal() as session:
                srow = await session.get(QuantStrategy, sid_uuid)
                if srow:
                    strategy_snapshot = dict(srow.config)
        except Exception:
            pass

    try:
        from datetime import date as _date
        import datetime as _dt
        async with AsyncSessionLocal() as session:
            bt_row = QuantBacktestRun(
                id=uuid.UUID(run_id),
                strategy_id=sid_uuid,
                strategy_snapshot=strategy_snapshot,
                symbol=req.symbol,
                timeframe=req.timeframe,
                start_date=_dt.date.fromisoformat(req.start_date),
                end_date=_dt.date.fromisoformat(req.end_date),
                starting_capital=req.starting_capital,
                parameters=parameters,
                status="queued",
            )
            session.add(bt_row)
            await session.commit()
    except Exception as db_exc:
        logger.warning("Failed to persist initial quant backtest record: %s", db_exc)

    _bt_runs_set(run_id, {
        "run_id":     run_id,
        "status":     "queued",
        "symbol":     req.symbol,
        "start_date": req.start_date,
        "end_date":   req.end_date,
        "queued_at":  datetime.now(timezone.utc).isoformat(),
        "disclaimer": "BACKTESTED — NOT LIVE PERFORMANCE",
    })

    asyncio.create_task(_run_backtest_task(run_id, req))
    return {**_bt_runs[run_id], "message": "Poll GET /api/quant/backtest/{run_id} for status."}


@router.get("/backtest/history")
async def get_backtest_history(limit: int = 20):
    """Return recent quant backtest runs."""
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(QuantBacktestRun)
                .order_by(desc(QuantBacktestRun.created_at))
                .limit(limit)
            )).scalars().all()

        return {
            "runs": [
                {
                    "run_id":          str(r.id),
                    "status":          r.status,
                    "symbol":          r.symbol,
                    "start_date":      str(r.start_date),
                    "end_date":        str(r.end_date),
                    "strategy_id":     str(r.strategy_id) if r.strategy_id else None,
                    "strategy_version": r.strategy_version,
                    "metrics":         r.metrics,
                    "queued_at":       r.created_at.isoformat() if r.created_at else None,
                    "completed_at":    r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in rows
            ],
            "total": len(rows),
        }
    except Exception:
        # DB unavailable — fall back to in-memory (do not expose exc details externally)
        runs = sorted(_bt_runs.values(), key=lambda r: r.get("queued_at", ""), reverse=True)
        return {"runs": runs[:limit], "total": len(runs), "warning": "Database unavailable — showing in-memory runs only"}


@router.get("/backtest/{run_id}")
async def get_backtest_result(run_id: str):
    """Get backtest result by run_id. Includes metrics, equity curve, and trade log."""
    if run_id in _bt_runs:
        return _bt_runs[run_id]

    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(QuantBacktestRun, uuid.UUID(run_id))
            if row:
                data = {
                    "run_id":          str(row.id),
                    "status":          row.status,
                    "symbol":          row.symbol,
                    "start_date":      str(row.start_date),
                    "end_date":        str(row.end_date),
                    "error":           row.error,
                    "equity_curve":    row.equity_curve or [],
                    "trades":          row.trades or [],
                    "disclaimer":      "BACKTESTED — NOT LIVE PERFORMANCE",
                    **(row.metrics or {}),
                }
                _bt_runs_set(run_id, data)
                return data
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Backtest run not found")


@router.get("/backtest/{run_id}/export")
async def export_backtest_trades(run_id: str):
    """Export the full trade log for a completed backtest as JSON."""
    result = await get_backtest_result(run_id)
    if result.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Backtest is not completed yet")
    return {
        "run_id":    run_id,
        "symbol":    result.get("symbol"),
        "disclaimer": "BACKTESTED — NOT LIVE PERFORMANCE",
        "trades":    result.get("trades", []),
    }
