"""
FastAPI application entry point.
All routes are registered here. Health check at GET /health.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    analytics,
    backtest,
    journal,
    market_data,
    paper_trade,
    research,
    risk,
    strategy,
    trading_mode,
)
from app.core.config import settings

app = FastAPI(
    title="OlbosQuant",
    version="3.0.0",
    description="Blessed prosperity through disciplined, rules-based quantitative trading.",
)

_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # Add production domain here: "https://olbosquant.io"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Route registration ─────────────────────────────────────────────────────
app.include_router(backtest.router,    prefix="/api/backtest",    tags=["Backtest"])
app.include_router(strategy.router,    prefix="/api/strategy",    tags=["Strategy"])
app.include_router(paper_trade.router, prefix="/api/paper-trade", tags=["Paper Trade"])
app.include_router(market_data.router, prefix="/api/market",      tags=["Market Data"])
app.include_router(risk.router,        prefix="/api/risk",         tags=["Risk"])
app.include_router(research.router,    prefix="/api/research",     tags=["Research"])
app.include_router(journal.router,     prefix="/api/journal",      tags=["Journal"])
app.include_router(analytics.router,   prefix="/api/analytics",    tags=["Analytics"])
app.include_router(trading_mode.router,prefix="/api/mode",         tags=["Trading Mode"])


# ── Health check ────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """Returns 200 OK when the service is up."""
    return {"status": "ok"}


# ── Guardrail status endpoint ───────────────────────────────────────────────
from app.services.guardrails import GuardrailEngine, PortfolioState

_guardrail_engine = GuardrailEngine()

@app.get("/api/guardrails/status", tags=["Guardrails"])
async def guardrail_status():
    """Returns current guardrail status using default portfolio state."""
    from app.core.config import settings
    portfolio = PortfolioState(
        current_value=settings.starting_capital,
        starting_capital=settings.starting_capital,
        daily_pnl=0.0, weekly_pnl=0.0, monthly_pnl=0.0,
        consecutive_losses=0, trades_today=0,
    )
    status = _guardrail_engine.check_all(portfolio)
    return {
        "trading_allowed": status.trading_allowed,
        "trading_mode": status.trading_mode,
        "reason": status.reason,
        "flags": status.flags,
        "daily_loss_pct": status.daily_loss_pct,
        "weekly_loss_pct": status.weekly_loss_pct,
        "monthly_loss_pct": status.monthly_loss_pct,
        "consecutive_losses": status.consecutive_losses,
        "trades_today": status.trades_today,
        "capital_pct_remaining": status.capital_pct_remaining,
    }


@app.get("/api/guardrails/history", tags=["Guardrails"])
async def guardrail_history():
    return {"events": []}


@app.get("/api/guardrails/trading-mode", tags=["Guardrails"])
async def trading_mode():
    from app.core.config import settings
    return {"mode": "normal", "signal_threshold": settings.signal_score_threshold}
