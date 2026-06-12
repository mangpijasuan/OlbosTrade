"""Research and strategy comparison routes."""
from fastapi import APIRouter
router = APIRouter()

@router.get("/comparison")
async def get_comparison():
    return {"comparison": None, "message": "Run /run-comparison first"}

@router.post("/run-comparison")
async def run_comparison(start_date: str = "2022-01-01", end_date: str = "2024-12-31"):
    return {"status": "queued", "start_date": start_date, "end_date": end_date}

@router.get("/model-performance")
async def get_model_performance():
    return {"model_version": "untrained", "auc": None, "last_trained": None}
