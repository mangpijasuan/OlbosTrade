"""Paper trading routes."""
from fastapi import APIRouter
router = APIRouter()

@router.get("/positions")
async def get_positions():
    return {"positions": []}

@router.get("/portfolio")
async def get_portfolio():
    return {"portfolio": {}}

@router.post("/toggle/{strategy}")
async def toggle_strategy(strategy: str):
    return {"strategy": strategy, "toggled": True}

@router.get("/history")
async def get_trade_history(limit: int = 50):
    return {"trades": [], "total": 0}

@router.get("/greeks-summary")
async def get_greeks_summary():
    return {"net_delta": 0, "net_theta": 0, "net_vega": 0, "net_gamma": 0}
