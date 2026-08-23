"""
Portfolio-level Trade Frequency Controller + Signal Ranking.

Sits in the pipeline BEFORE the risk engine:

    Signal Generation → Signal Ranking → Trade Frequency Controller
    → Risk Engine → Portfolio Engine → Execution → IBKR

Purpose: profitability before activity. It ranks candidate signals by a weighted
quality score and throttles execution per the active risk mode (Conservative /
Balanced / Aggressive) — enforcing per-mode daily caps, a minimum confidence, a
maximum risk score, and a positive-expected-value quality filter. It NEVER
manufactures trades: if nothing qualifies, nothing trades.

This complements (does not replace) the existing GuardrailEngine, which keeps
veto authority over loss limits, drawdown, cooling-off, and concentration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.trading_mode import TradingModeType, trading_mode_manager
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Per-mode frequency / quality rules ──────────────────────────────────────────
@dataclass(frozen=True)
class FrequencyRule:
    target_per_day:        int     # soft target (informational)
    hard_max_per_day:      int     # hard cap — never exceeded
    min_confidence:        float   # 0..1 minimum signal confidence to qualify
    max_risk_score:        int     # 0..100 maximum acceptable risk score
    capital_deploy_min:    float   # informational deployment band (0..1)
    capital_deploy_max:    float
    min_pop:               float = 0.0  # 0..1 minimum probability-of-profit (options)


MODE_RULES: dict[TradingModeType, FrequencyRule] = {
    # 2026-07-28 max-trades-per-day adjustment (operator request: "conservative
    # is 1, balanced is 5, aggressive is 10") — hard_max_per_day is the real
    # enforced daily cap; target_per_day trimmed to 1 alongside it so the
    # informational soft target never exceeds the hard cap it sits under.
    TradingModeType.CONSERVATIVE: FrequencyRule(
        target_per_day=1, hard_max_per_day=1, min_confidence=0.90,
        max_risk_score=20, capital_deploy_min=0.20, capital_deploy_max=0.40,
        min_pop=0.75),
    TradingModeType.BALANCED: FrequencyRule(
        target_per_day=2, hard_max_per_day=5, min_confidence=0.90,
        max_risk_score=20, capital_deploy_min=0.20, capital_deploy_max=0.40,
        min_pop=0.75),
    TradingModeType.AGGRESSIVE: FrequencyRule(
        target_per_day=6, hard_max_per_day=10, min_confidence=0.70,
        max_risk_score=40, capital_deploy_min=0.40, capital_deploy_max=0.70,
        min_pop=0.65),
    # Scalper inherits aggressive-style frequency but keeps the tightest cap;
    # min_confidence loosened slightly (was 0.65).
    TradingModeType.SCALPER: FrequencyRule(
        target_per_day=20, hard_max_per_day=40, min_confidence=0.60,
        max_risk_score=60, capital_deploy_min=0.50, capital_deploy_max=0.95,
        min_pop=0.0),
}


# Strategy-level minimum probability-of-profit, applied in EVERY mode (the
# effective floor is max(mode.min_pop, strategy floor)). Premium-selling spreads
# only earn their edge from a high win rate, so we never let them through below
# 70% POP — even in Aggressive mode. Debit spreads are intentionally low-POP /
# high-payoff and carry no floor.
STRATEGY_MIN_POP: dict[str, float] = {
    "bull_put_spread":  0.70,
    "bear_call_spread": 0.70,
    "iron_condor":      0.70,
}


def rule_for(mode: TradingModeType) -> FrequencyRule:
    return MODE_RULES.get(mode, MODE_RULES[TradingModeType.BALANCED])


# ── Signal scoring (used for ranking + the quality filter) ──────────────────────
def _confidence(signal: dict) -> float:
    """Unified 0..1 confidence — equities use 'confidence', options 'signal_score'."""
    c = signal.get("confidence")
    if c is None:
        c = signal.get("signal_score", 0.0)
    try:
        return max(0.0, min(1.0, float(c)))
    except (TypeError, ValueError):
        return 0.0


def _reward_risk(signal: dict) -> float:
    """Reward:risk ratio. Equity: trade_plan.risk_reward. Options: credit/max_loss."""
    tp = signal.get("trade_plan") or {}
    if tp.get("risk_reward") is not None:
        try:
            return max(0.0, float(tp["risk_reward"]))
        except (TypeError, ValueError):
            return 0.0
    spread = signal.get("spread") or {}
    credit = float(spread.get("net_credit", 0) or 0)
    max_loss = float(spread.get("max_loss", 0) or 0)
    if max_loss > 0:
        return max(0.0, credit / max_loss)
    return 0.0


def _liquidity(signal: dict) -> float:
    """0..1 liquidity proxy. Equity: volume_ratio (capped). Options: 0.5 placeholder
    until the Options Intelligence engine supplies real bid/ask depth."""
    ind = signal.get("indicators") or {}
    vr = ind.get("volume_ratio")
    if vr is not None:
        try:
            return max(0.0, min(1.0, float(vr) / 2.0))  # 2x avg volume ⇒ 1.0
        except (TypeError, ValueError):
            return 0.5
    return 0.5


def expected_value(signal: dict) -> float:
    """
    Per-$1-risk expected value proxy: EV = p·reward − (1−p)·1, where p is the
    confidence used as a probability-of-profit proxy. Refined later by the
    Options Intelligence engine (true POP). EV > 0 is the quality gate.
    """
    p = _confidence(signal)
    rr = _reward_risk(signal)
    return round(p * rr - (1.0 - p), 4)


def _regime_score(signal: dict) -> float:
    """
    0..1 regime-alignment factor. 1.0 when the signal's strategy is sanctioned by
    the current regime, 0.3 when it runs against the regime, 0.0 in a crisis
    (nothing is sanctioned), and 0.5 when the regime is unknown/absent. An
    explicit signal['regime_score'] (0..1) overrides the lookup.
    """
    override = signal.get("regime_score")
    if override is not None:
        try:
            return max(0.0, min(1.0, float(override)))
        except (TypeError, ValueError):
            pass
    regime = signal.get("regime")
    strategy = signal.get("strategy") or ""
    if not regime or not strategy:
        return 0.5
    try:
        from app.services.regime_classifier import REGIME_CONFIG, RegimeType
        cfg = REGIME_CONFIG.get(RegimeType(regime))
    except Exception:
        return 0.5
    if not cfg:   # pragma: no cover - every valid RegimeType has a config entry
        return 0.5
    allowed = set(cfg.get("strategies_allowed", [])) | set(
        cfg.get("equity_strategies_allowed", []))
    if not allowed:            # crisis → nothing sanctioned
        return 0.0
    return 1.0 if strategy in allowed else 0.3


def score_components(signal: dict) -> dict:
    """
    The five normalized (0..1) sub-scores weighted_score() combines, exposed
    individually so callers (e.g. opportunity_score.py) can show a breakdown
    instead of just the final number. Single source of truth for both.
    """
    conf = _confidence(signal)
    ev = expected_value(signal)
    ev_score = max(0.0, min(1.0, (ev + 1.0) / 2.0))   # map EV∈[-1,1] → [0,1]
    rr_score = max(0.0, min(1.0, _reward_risk(signal) / 3.0))  # 3:1 ⇒ 1.0
    liq = _liquidity(signal)
    reg = _regime_score(signal)
    return {
        "confidence": conf,
        "ev": ev_score,
        "reward_risk": rr_score,
        "liquidity": liq,
        "regime": reg,
    }


def weighted_score(signal: dict) -> float:
    """
    Ranking score (0..1-ish): 0.35 confidence + 0.25 EV + 0.15 reward:risk
    + 0.15 liquidity + 0.10 regime alignment. Higher ranks execute first.
    """
    c = score_components(signal)
    return round(0.35 * c["confidence"] + 0.25 * c["ev"] + 0.15 * c["reward_risk"]
                 + 0.15 * c["liquidity"] + 0.10 * c["regime"], 4)


def risk_score(signal: dict) -> int:
    """
    0..100 risk score (higher = riskier). v1: inverse of confidence, nudged up by
    a poor reward:risk. Enriched later with position size / spread width / Greeks.
    """
    base = (1.0 - _confidence(signal)) * 100.0
    rr = _reward_risk(signal)
    if rr and rr < 1.0:
        base += (1.0 - rr) * 15.0   # sub-1:1 reward:risk adds risk
    return int(max(0, min(100, round(base))))


@dataclass
class GateDecision:
    allowed: bool
    reason: str
    weighted_score: float
    risk_score: int
    expected_value: float


class TradeFrequencyController:
    """Stateless gate + ranker. Daily count is supplied by the caller (DB-backed)."""

    @staticmethod
    def _pop(signal: dict) -> Optional[float]:
        """Probability-of-profit if present (options), else None (equities)."""
        p = signal.get("pop")
        if p is None:
            return None
        try:
            return max(0.0, min(1.0, float(p)))
        except (TypeError, ValueError):
            return None

    def rank(self, signals: list[dict]) -> list[dict]:
        """Highest-quality first."""
        return sorted(signals, key=weighted_score, reverse=True)

    def evaluate(
        self,
        signal: dict,
        trades_today: int,
        mode: Optional[TradingModeType] = None,
    ) -> GateDecision:
        if mode is None:
            mode = trading_mode_manager.current.active_mode
        rule = rule_for(mode)

        ws = weighted_score(signal)
        rs = risk_score(signal)
        ev = expected_value(signal)
        conf = _confidence(signal)

        # PAPER validation: bypass the quality/frequency filters so the pipeline
        # actually trades. Hard safety rails (kill switch, paper guard, market
        # hours, margin, sizing) still apply downstream in handle_signal.
        from app.core.config import settings as _cfg
        if getattr(_cfg, "execution_test_mode", False):
            return GateDecision(True, "execution_test_mode", ws, rs, ev)

        # 1. Hard daily cap — never exceeded (profitability before activity).
        if trades_today >= rule.hard_max_per_day:
            return GateDecision(False,
                f"daily_cap: {trades_today}/{rule.hard_max_per_day} for {mode.value}",
                ws, rs, ev)

        # 2. Minimum confidence for the mode.
        if conf < rule.min_confidence:
            return GateDecision(False,
                f"below_min_confidence: {conf:.2f} < {rule.min_confidence:.2f} ({mode.value})",
                ws, rs, ev)

        # 2b. Probability-of-profit floor (options only; equities carry no POP).
        # Effective floor = max(mode floor, strategy floor). Skipped when the
        # signal has no POP, so equity signals are unaffected.
        pop = self._pop(signal)
        if pop is not None:
            pop_floor = max(rule.min_pop,
                            STRATEGY_MIN_POP.get(signal.get("strategy", ""), 0.0))
            if pop < pop_floor:
                return GateDecision(False,
                    f"pop_below_floor: {pop:.2f} < {pop_floor:.2f} ({mode.value})",
                    ws, rs, ev)

        # 3. Maximum risk score for the mode.
        if rs > rule.max_risk_score:
            return GateDecision(False,
                f"risk_score_too_high: {rs} > {rule.max_risk_score} ({mode.value})",
                ws, rs, ev)

        # 4. Positive expected value — quality filter (never trade negative EV).
        if ev <= 0:
            return GateDecision(False, f"non_positive_ev: {ev}", ws, rs, ev)

        return GateDecision(True, "ok", ws, rs, ev)


# ── Singleton ───────────────────────────────────────────────────────────────────
trade_frequency_controller = TradeFrequencyController()
