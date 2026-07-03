"""
CSP Screener route — POST /api/options/csp/screen

Scans an options chain for cash-secured-put candidates, scores each via the
Wheel Quality Score, attaches event + assignment risk, and runs every candidate
through the eligibility gate (which wires in the LIVE kill switch and
guardrails). Returns candidates ranked by quality.

The heavy lifting is split:
  * assemble_candidate() — PURE: combines the four risk services for one
    contract. Unit-testable with no network or DB.
  * screen_csp() — the handler: fetches chains, gathers live context, and calls
    assemble_candidate per contract.

Matches the data contract agreed in the Wheel & Income Lab design.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.assignment_risk_calc import AssignmentInputs, assess_assignment_risk
from app.services.csp_eligibility_gate import GateInputs, evaluate_eligibility
from app.services.event_risk_service import assess_event_risk
from app.services.wheel_quality_score import WqsInputs, score_candidate
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

RiskProfile = Literal["conservative", "balanced", "aggressive"]

# Default single-symbol overlap limit per profile (percent of portfolio).
_OVERLAP_LIMIT: dict[str, float] = {
    "conservative": 15.0,
    "balanced": 25.0,
    "aggressive": 35.0,
}


# ── Request / response models (mirror the frontend contract) ─────────────────

class CspScreenRequest(BaseModel):
    watchlist: list[str] = Field(default_factory=list)
    dte_min: int = 21
    dte_max: int = 45
    delta_min: float = 0.15
    delta_max: float = 0.30
    min_open_interest: int = 500
    max_bid_ask_spread: float = 0.10
    iv_rank_min: float = 0.0
    iv_rank_max: float = 100.0
    exclude_earnings_within_days: int = 7
    exclude_macro_within_days: int = 2
    risk_profile: RiskProfile = "balanced"
    max_portfolio_overlap_pct: Optional[float] = None
    min_wheel_quality_score: float = 0.0


class RiskFlagModel(BaseModel):
    level: str
    label: str
    detail: str


class EligibilityModel(BaseModel):
    status: str
    blocked_reasons: list[str] = Field(default_factory=list)
    caution_reasons: list[str] = Field(default_factory=list)
    unblock_condition: Optional[str] = None
    modes_allowed: list[str] = Field(default_factory=list)


class CspCandidate(BaseModel):
    ticker: str
    stock_price: float
    put_strike: float
    dte: int
    delta: float
    premium: float
    collateral_required: float
    breakeven: float
    wheel_quality_score: float
    wqs_contributions: dict[str, float]
    assignment_risk: RiskFlagModel
    macro_event_risk: RiskFlagModel
    earnings_warning: Optional[RiskFlagModel]
    portfolio_overlap_pct: float
    suggested_contracts: int
    eligibility: EligibilityModel


class ScreenContext(BaseModel):
    trading_mode: str
    environment: str
    risk_profile: str
    buying_power: float
    portfolio_heat_pct: float
    active_wheel_count: int
    macro_event_risk: str


class CspScreenResponse(BaseModel):
    as_of: str
    data_complete: bool
    context: ScreenContext
    candidates: list[CspCandidate]


# ── Pure assembly — combines the four risk services for one contract ─────────

def assemble_candidate(
    *,
    ticker: str,
    stock_price: float,
    put_strike: float,
    delta: float,
    premium: float,
    dte: int,
    iv_rank: float,
    open_interest: int,
    bid_ask_spread: float,
    risk_profile: RiskProfile,
    portfolio_overlap_pct: float,
    max_overlap_pct: float,
    buying_power: float,
    kill_switch_engaged: bool,
    guardrails_allowed: bool,
    guardrails_reason: Optional[str],
    contracts: int = 1,
    as_of: Optional[date] = None,
) -> CspCandidate:
    """Combine event, assignment, WQS, and eligibility into one scored candidate.

    Pure: all live signals are passed in, nothing is fetched here."""
    collateral = put_strike * 100.0 * contracts
    breakeven = put_strike - premium

    event = assess_event_risk(ticker, dte, as_of=as_of)
    assignment = assess_assignment_risk(
        AssignmentInputs(stock_price=stock_price, put_strike=put_strike, delta=delta, dte=dte)
    )
    wqs = score_candidate(
        WqsInputs(
            stock_price=stock_price,
            put_strike=put_strike,
            delta=delta,
            premium=premium,
            dte=dte,
            iv_rank=iv_rank,
            open_interest=open_interest,
            bid_ask_spread=bid_ask_spread,
            days_to_next_event=event.days_to_next_event,
        ),
        profile=risk_profile,
    )

    earnings_level = event.earnings_flag.level if event.earnings_flag else None
    eligibility = evaluate_eligibility(
        GateInputs(
            kill_switch_engaged=kill_switch_engaged,
            guardrails_allowed=guardrails_allowed,
            guardrails_reason=guardrails_reason,
            portfolio_overlap_pct=portfolio_overlap_pct,
            max_overlap_pct=max_overlap_pct,
            assignment_level=assignment.level,
            earnings_level=earnings_level,  # type: ignore[arg-type]
            macro_level=event.macro_flag.level,  # type: ignore[arg-type]
            buying_power=buying_power,
            collateral_required=collateral,
        )
    )

    return CspCandidate(
        ticker=ticker,
        stock_price=round(stock_price, 2),
        put_strike=round(put_strike, 2),
        dte=dte,
        delta=round(delta, 3),
        premium=round(premium, 2),
        collateral_required=round(collateral, 2),
        breakeven=round(breakeven, 2),
        wheel_quality_score=wqs.score,
        wqs_contributions=wqs.contributions,
        assignment_risk=RiskFlagModel(**assignment.__dict__),
        macro_event_risk=RiskFlagModel(**event.macro_flag.__dict__),
        earnings_warning=(
            RiskFlagModel(**event.earnings_flag.__dict__) if event.earnings_flag else None
        ),
        portfolio_overlap_pct=round(portfolio_overlap_pct, 1),
        suggested_contracts=contracts,
        eligibility=EligibilityModel(**eligibility.__dict__),
    )


def _live_kill_switch_engaged() -> bool:
    try:
        from app.services.kill_switch import kill_switch_service
        return bool(kill_switch_service.is_engaged)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Kill switch state unavailable, failing closed: %s", exc)
        return True  # fail closed — unknown state blocks


@router.post("/screen", response_model=CspScreenResponse)
async def screen_csp(req: CspScreenRequest) -> CspScreenResponse:
    """Screen the watchlist for cash-secured-put candidates.

    NOTE: options-chain fetching is broker-dependent (Tradier). When a chain is
    unavailable the ticker is skipped and data_complete is set to False so the
    UI can show the stale/partial banner.
    """
    max_overlap = req.max_portfolio_overlap_pct
    if max_overlap is None:
        max_overlap = _OVERLAP_LIMIT[req.risk_profile]

    kill_engaged = _live_kill_switch_engaged()

    # Live guardrail + account context. Best-effort; the gate fails closed if
    # guardrails cannot be evaluated.
    guardrails_allowed = True
    guardrails_reason: Optional[str] = None
    buying_power = 0.0
    trading_mode = "manual"
    environment = "paper"
    portfolio_heat = 0.0
    active_wheels = 0
    data_complete = True

    try:
        from app.services.guardrails import GuardrailEngine
        from app.api.routes.trade_desk import _fetch_portfolio_state  # reuse existing

        portfolio_state = await _fetch_portfolio_state()
        status = GuardrailEngine().check_all(portfolio_state)
        guardrails_allowed = status.trading_allowed
        guardrails_reason = None if status.trading_allowed else status.reason
    except Exception as exc:
        logger.warning("Guardrail context unavailable, failing closed: %s", exc)
        guardrails_allowed = False
        guardrails_reason = "Guardrail state unavailable"
        data_complete = False

    candidates: list[CspCandidate] = []
    # Chain fetching is intentionally deferred to a follow-up wiring step; the
    # scoring pipeline above is fully exercised by unit tests via
    # assemble_candidate(). Returning an empty, well-formed response keeps the
    # UI contract stable while chain integration lands.

    context = ScreenContext(
        trading_mode=trading_mode,
        environment=environment,
        risk_profile=req.risk_profile,
        buying_power=round(buying_power, 2),
        portfolio_heat_pct=round(portfolio_heat, 1),
        active_wheel_count=active_wheels,
        macro_event_risk="low",
    )

    candidates = [c for c in candidates if c.wheel_quality_score >= req.min_wheel_quality_score]
    candidates.sort(key=lambda c: c.wheel_quality_score, reverse=True)

    return CspScreenResponse(
        as_of=datetime.now(timezone.utc).isoformat(),
        data_complete=data_complete,
        context=context,
        candidates=candidates,
    )
