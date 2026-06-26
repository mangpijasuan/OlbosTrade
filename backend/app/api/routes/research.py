"""Research routes — strategy comparison, model performance, and the Research Lab."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

# In-memory store for comparison results
_comparison_result: dict | None = None
_comparison_running: bool = False


async def _run_comparison_task(start_date: str, end_date: str, capital: float) -> None:
    global _comparison_result, _comparison_running
    _comparison_running = True
    try:
        from app.broker.broker_factory import get_broker
        from app.services.data_fetcher import DataFetcher
        from app.services.backtester import Backtester

        broker  = get_broker()
        fetcher = DataFetcher(broker)
        bt      = Backtester(fetcher)

        strategies = ["bull_put_spread", "bear_call_spread", "iron_condor", "bull_call_debit_spread"]
        results = {}
        for strat in strategies:
            try:
                r = await bt.run(strat, start_date, end_date, capital)
                m = r.metrics
                total_pnl = r.ending_capital - r.starting_capital
                results[strat] = {
                    "total_trades":     m.total_trades if m else len(r.trades),
                    "win_rate":         round(m.win_rate, 4) if m else 0.0,
                    "total_pnl":        round(total_pnl, 2),
                    "total_return_pct": round(m.total_return_pct, 4) if m else 0.0,
                    "max_drawdown_pct": round(m.max_drawdown_pct, 4) if m else 0.0,
                    "sharpe_ratio":     round(m.sharpe_ratio, 4) if m else 0.0,
                    "profit_factor":    round(m.profit_factor, 4) if m else 0.0,
                }
            except Exception as exc:
                results[strat] = {"error": str(exc)}

        # Rank by total_pnl
        ranked = sorted(
            [(s, d) for s, d in results.items() if "error" not in d],
            key=lambda x: x[1].get("total_pnl", 0), reverse=True
        )
        _comparison_result = {
            "status":       "completed",
            "start_date":   start_date,
            "end_date":     end_date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "results":      results,
            "ranking":      [s for s, _ in ranked],
            "best_strategy": ranked[0][0] if ranked else None,
        }
    except Exception as exc:
        _comparison_result = {"status": "failed", "error": str(exc)}
    finally:
        _comparison_running = False


@router.get("/comparison")
async def get_comparison():
    if _comparison_result is None:
        return {"comparison": None, "message": "Run POST /api/research/run-comparison first."}
    return {"comparison": _comparison_result}


@router.post("/run-comparison")
async def run_comparison(
    start_date: str = "2023-01-01",
    end_date:   str = "2024-12-31",
    starting_capital: float = 25000.0,
):
    global _comparison_running
    if _comparison_running:
        return {"status": "already_running", "message": "Comparison already in progress."}
    asyncio.create_task(_run_comparison_task(start_date, end_date, starting_capital))
    return {
        "status":     "running",
        "start_date": start_date,
        "end_date":   end_date,
        "message":    "Poll GET /api/research/comparison for results.",
    }


@router.get("/model-performance")
async def get_model_performance():
    """Return signal scorer model metadata."""
    try:
        from app.services.signal_scorer import SignalScorer
        from app.core.config import settings
        import os
        scorer = SignalScorer()
        trained = os.path.exists(settings.model_path)
        return {
            "model_version":  "v1" if trained else "untrained",
            "model_path":     settings.model_path,
            "trained":        trained,
            "auc":            getattr(scorer, "auc", None),
            "last_trained":   getattr(scorer, "last_trained", None),
            "retrain_schedule": settings.retrain_schedule,
        }
    except Exception as exc:
        return {"model_version": "untrained", "auc": None, "last_trained": None, "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# Research Lab — strategy promotion funnel (draft → backtested → paper → promoted)
# ══════════════════════════════════════════════════════════════════════════════
class CreateExperiment(BaseModel):
    name:       str
    strategy:   str
    hypothesis: Optional[str] = None
    spec:       Optional[dict] = None
    # Registry metadata (Phase 2) — optional at creation, required before promotion.
    version:     Optional[str] = None
    author:      Optional[str] = None
    asset_class: Optional[str] = None
    market_type: Optional[str] = None
    supported_regimes: Optional[list] = None
    risk_profile: Optional[str] = None


class TransitionRequest(BaseModel):
    target:     str                    # backtested | walk_forward | paper | promoted | archived | draft
    metrics:    Optional[dict] = None   # backtest metrics (→ backtested / → walk_forward)
    wf_metrics: Optional[dict] = None   # walk-forward (out-of-sample) metrics (→ paper)
    perf:       Optional[dict] = None    # paper performance (→ promoted)


async def _experiment_or_none(session, exp_id: str):
    from app.models.research_experiment import ResearchExperiment
    from sqlalchemy import select
    return (await session.execute(
        select(ResearchExperiment).where(ResearchExperiment.id == exp_id)
    )).scalar_one_or_none()


@router.get("/lab/experiments")
async def list_experiments():
    """All Research Lab experiments, newest first."""
    from app.core.database import AsyncSessionLocal
    from app.models.research_experiment import ResearchExperiment
    from sqlalchemy import select
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(ResearchExperiment).order_by(ResearchExperiment.created_at.desc())
            )).scalars().all()
        return {"experiments": [r.as_dict() for r in rows], "total": len(rows)}
    except Exception as exc:
        return {"experiments": [], "total": 0, "error": str(exc)}


@router.post("/lab/experiments")
async def create_experiment(req: CreateExperiment):
    """Create a DRAFT experiment from a hypothesis + Symphony spec."""
    from app.core.database import AsyncSessionLocal
    from app.models.research_experiment import ResearchExperiment
    from app.services.research_lab import DRAFT
    try:
        exp = ResearchExperiment(
            name=req.name, strategy=req.strategy, hypothesis=req.hypothesis,
            stage=DRAFT, spec=req.spec, version=req.version, author=req.author,
            asset_class=req.asset_class, market_type=req.market_type,
            supported_regimes=req.supported_regimes, risk_profile=req.risk_profile,
        )
        async with AsyncSessionLocal() as session:
            session.add(exp)
            await session.commit()
            await session.refresh(exp)
        return exp.as_dict()
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/lab/experiments/{exp_id}/transition")
async def transition_experiment(exp_id: str, req: TransitionRequest):
    """
    Advance an experiment through the funnel. Gates are enforced server-side:
    a move to PAPER needs a passing backtest, to PROMOTED a passing paper record.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.research_lab import transition
    try:
        async with AsyncSessionLocal() as session:
            exp = await _experiment_or_none(session, exp_id)
            if exp is None:
                return {"error": "experiment not found"}
            result = transition(exp.as_dict(), req.target,
                                metrics=req.metrics, wf_metrics=req.wf_metrics,
                                perf=req.perf)
            if not result.ok:
                return {"ok": False, "reason": result.reason, "experiment": exp.as_dict()}
            for k, v in result.patch.items():
                setattr(exp, k, v)
            await session.commit()
            await session.refresh(exp)
        return {"ok": True, "reason": result.reason, "experiment": exp.as_dict()}
    except Exception as exc:
        return {"ok": False, "reason": f"error: {exc}", "experiment": None}


@router.get("/lab/baselines")
async def lab_baselines():
    """
    StrategyBaseline overrides derived from PROMOTED experiments — the bridge that
    feeds the Strategy Health Monitor real, evidence-based baselines.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.research_experiment import ResearchExperiment
    from app.services.research_lab import baselines_from_experiments, PROMOTED
    from sqlalchemy import select
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(ResearchExperiment).where(ResearchExperiment.stage == PROMOTED)
            )).scalars().all()
        baselines = baselines_from_experiments([r.as_dict() for r in rows])
        return {"baselines": {k: {"win_rate": v.win_rate, "expectancy": v.expectancy,
                                  "max_drawdown_pct": v.max_drawdown_pct}
                              for k, v in baselines.items()}}
    except Exception as exc:
        return {"baselines": {}, "error": str(exc)}


@router.get("/registry")
async def get_registry():
    """
    Canonical Strategy Registry view: every strategy's most-advanced lifecycle
    stage, experiment counts, production set, and metadata-completeness flags.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.research_experiment import ResearchExperiment
    from app.services import strategy_registry as reg
    from sqlalchemy import select
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(ResearchExperiment).order_by(ResearchExperiment.created_at.desc())
            )).scalars().all()
        exps = [r.as_dict() for r in rows]
        strategies = reg.by_strategy(exps)
        # Annotate each experiment's metadata completeness for the UI.
        for s in strategies.values():
            members = [e for e in exps if e.get("strategy") == s["strategy"]]
            complete = any(reg.validate_metadata(e)[0] for e in members)
            s["metadata_complete"] = complete
        return {"summary": reg.summarize(exps),
                "strategies": list(strategies.values())}
    except Exception as exc:
        return {"summary": {}, "strategies": [], "error": str(exc)}


@router.get("/features")
async def get_features():
    """Feature Store catalog — the single registry of indicator/feature formulas."""
    from app.services.feature_store import catalog
    return {"features": catalog(), "total": len(catalog())}


# ══════════════════════════════════════════════════════════════════════════════
# AI Research Assistant — read-only Q&A grounded in live system data
# ══════════════════════════════════════════════════════════════════════════════
class AssistantRequest(BaseModel):
    question: str


async def _assistant_context() -> str:
    """Compact, grounded snapshot the LLM may reason over (no raw PII)."""
    import json
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.journal_intelligence import analyze
    from sqlalchemy import select

    parts: list[str] = []
    try:
        async with AsyncSessionLocal() as session:
            trades = (await session.execute(
                select(Trade).where(Trade.status == "closed", Trade.pnl.isnot(None))
            )).scalars().all()
        rows = [{"pnl": float(t.pnl), "strategy": t.strategy, "regime": t.regime
                 if hasattr(t, "regime") else None,
                 "signal_score": float(t.signal_score) if t.signal_score is not None else None,
                 "entry_date": t.entry_date, "exit_date": t.exit_date} for t in trades]
        parts.append("JOURNAL_INTELLIGENCE:\n" + json.dumps(analyze(rows), default=str))
    except Exception as exc:
        parts.append(f"JOURNAL_INTELLIGENCE: unavailable ({exc})")

    try:
        from app.main import _current_regime
        regime = getattr(getattr(_current_regime, "regime", None), "value", None)
        parts.append(f"CURRENT_REGIME: {regime}")
    except Exception:
        pass
    return "\n\n".join(parts)


@router.post("/assistant")
async def research_assistant(req: AssistantRequest):
    """
    Conversational research over the platform's own data. Provider-agnostic
    (Gemini by default; Claude optional). Degrades gracefully when no key is set.
    """
    from app.core.config import settings
    from app.services.llm_provider import generate, LLMUnavailable

    if not req.question.strip():
        return {"error": "empty question"}

    context = await _assistant_context()
    try:
        result = generate(
            req.question, context,
            provider=settings.llm_provider,
            anthropic_key=settings.anthropic_api_key or None,
            gemini_key=settings.gemini_api_key or None,
            model=settings.llm_model or None,
        )
        return result
    except LLMUnavailable as exc:
        return {"error": f"assistant unavailable: {exc}",
                "hint": "Set GEMINI_API_KEY (free tier) or ANTHROPIC_API_KEY in .env.prod"}
    except Exception as exc:
        return {"error": f"assistant error: {exc}"}
