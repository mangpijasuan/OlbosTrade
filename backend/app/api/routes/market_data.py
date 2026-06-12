"""Market data routes."""
from fastapi import APIRouter
router = APIRouter()

@router.get("/snapshot/{symbol}")
async def get_snapshot(symbol: str):
    return {"symbol": symbol, "snapshot": {}}

@router.get("/options-chain/{symbol}")
async def get_options_chain(symbol: str, expiry: str = ""):
    return {"symbol": symbol, "chain": {}}

@router.get("/iv-rank/{symbol}")
async def get_iv_rank(symbol: str):
    return {"symbol": symbol, "iv_rank": None, "iv_percentile": None}
