"""Alpha Edge Signal routes — see app/services/alpha_edge_engine.py for the
scoring design and what's deliberately out of scope for this first slice."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query

router = APIRouter()


def _result_to_dict(result) -> dict:
    d = asdict(result)
    d["score_trend"] = asdict(result.score_trend)
    return d


@router.get("/{ticker}")
async def get_alpha_edge(ticker: str, asset_type: str = Query("equity", pattern="^(equity|options)$")):
    """Live, on-demand Alpha Edge scores for one symbol — see
    alpha_edge_engine.py for exactly what each score is derived from."""
    from app.services import alpha_edge_engine

    if asset_type == "options":
        result = await alpha_edge_engine.compute_options_alpha_edge(ticker)
    else:
        broker = None
        try:
            from app.broker.broker_factory import get_broker
            broker = get_broker()
        except Exception:
            pass
        result = await alpha_edge_engine.compute_equity_alpha_edge(ticker, broker=broker)

    return _result_to_dict(result)
