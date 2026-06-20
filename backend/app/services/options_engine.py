"""
Alpha Options — unified intelligence pipeline for 0DTE–60DTE SPY spreads.

Single entry point used by the background scheduler. Replaces the legacy
simplified _run_options_scan() path with full regime → strategy → AI →
trading-mode → flow → execution routing through trade_desk.handle_signal().
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from app.broker.broker_interface import Greeks, OptionContract, OptionsChain
from app.core.config import settings
from app.services.data_fetcher import DataFetcher
from app.services.guardrails import GuardrailEngine, PortfolioState
from app.services.options_pricer import BlackScholesPricer
from app.services.regime_classifier import RegimeState, compute_flow_features
from app.services.risk_manager import PortfolioRiskState
from app.services.signal_scorer import SignalFeatures, SignalScorer
from app.services.strategy_engine import (
    BearCallSpread,
    BullCallDebitSpread,
    BullPutSpread,
    IronCondor,
    Signal,
    approve_trade,
)
from app.services.trading_mode import (
    is_strategy_allowed_by_mode,
    select_expiry_within_bounds,
    trading_mode_manager,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

STRATEGY_MAP = {
    "bull_put_spread":        BullPutSpread(),
    "bear_call_spread":       BearCallSpread(),
    "iron_condor":            IronCondor(),
    "bull_call_debit_spread": BullCallDebitSpread(),
}

RISK_FREE = 0.05


class OptionsEngine:
    """Mode-aware options signal generation and routing."""

    def __init__(self) -> None:
        self.scorer = SignalScorer()
        self.guardrails = GuardrailEngine()
        self.fetcher = DataFetcher()
        self.pricer = BlackScholesPricer()

    async def scan(self, regime: RegimeState) -> list[dict]:
        """
        Run a full options intelligence cycle for the current regime.
        Returns action records for logging; routes approved signals to trade desk.
        """
        actions: list[dict] = []

        if regime is None or not getattr(regime, "options_allowed", False):
            return actions

        mode_cfg = trading_mode_manager.config
        expiry, actual_dte = select_expiry_within_bounds(
            mode_cfg.dte_target,
            mode_cfg.dte_min,
            mode_cfg.dte_max,
        )
        if expiry is None or actual_dte is None:
            logger.warning(
                "No valid expiry in DTE range %d–%d for mode %s",
                mode_cfg.dte_min, mode_cfg.dte_max, mode_cfg.mode.value,
            )
            return [{"action": "skipped", "reason": "no_valid_expiry"}]

        try:
            portfolio_state = await self._load_portfolio_state()
            guardrail_status = self.guardrails.check_all(portfolio_state)
            if not guardrail_status.trading_allowed:
                return [{"action": "blocked", "reason": guardrail_status.reason}]

            spy_price, market = await self._load_market_data()
            if spy_price is None:
                return [{"action": "skipped", "reason": "market_data_unavailable"}]
            market["spot"] = spy_price

            chain = await self._load_chain("SPY", expiry, spy_price, market["sigma"])
            if chain is None:
                return [{"action": "skipped", "reason": "chain_unavailable"}]

            portfolio_risk = PortfolioRiskState(
                net_delta=0.0,
                net_vega=0.0,
                net_theta=0.0,
                open_position_count=await self._count_open_positions(),
                portfolio_value=portfolio_state.current_value,
                positions_by_underlying={},
                positions_by_sector={},
            )

            flow_feats = await compute_flow_features("SPY")
            effective_threshold = max(
                self.guardrails.get_signal_threshold(guardrail_status),
                regime.signal_threshold or 0.0,
            )

            allowed_strategies = [
                s for s in (regime.strategies_allowed or [])
                if is_strategy_allowed_by_mode(s)
            ]

            for strategy_name in allowed_strategies:
                strategy_obj = STRATEGY_MAP.get(strategy_name)
                if strategy_obj is None:
                    continue

                if not self.guardrails.is_strategy_allowed(strategy_name, guardrail_status):
                    actions.append({
                        "action": "blocked",
                        "strategy": strategy_name,
                        "reason": "guardrail_risk_state",
                    })
                    continue

                signal = strategy_obj.generate_signal(
                    chain=chain,
                    iv_rank=market["iv_rank"],
                    rsi=market["rsi"],
                    adx=market["adx"],
                    above_sma20=market["above_sma20"],
                    vix=market["vix"],
                    portfolio_state=portfolio_state,
                )

                if not signal.entry_allowed:
                    continue

                flow_ok, flow_reason = self._check_flow_gate(
                    strategy_name, flow_feats, signal.direction,
                )
                if not flow_ok:
                    actions.append({
                        "action": "flow_blocked",
                        "strategy": strategy_name,
                        "reason": flow_reason,
                    })
                    continue

                features = self._build_features(
                    signal, market, actual_dte, flow_feats,
                )
                score_result = await self.scorer.score_async(
                    features, effective_threshold,
                )
                if not score_result.approved:
                    actions.append({
                        "action": "signal_rejected",
                        "strategy": strategy_name,
                        "score": score_result.score,
                        "threshold": effective_threshold,
                        "reason": score_result.rejection_reason,
                    })
                    continue

                approved, checklist_reason = approve_trade(
                    signal=signal,
                    portfolio_state=portfolio_state,
                    portfolio_risk=portfolio_risk,
                    signal_score=score_result.score,
                    guardrail_engine=self.guardrails,
                    risk_manager=strategy_obj.risk_manager,
                )
                if not approved:
                    actions.append({
                        "action": "checklist_rejected",
                        "strategy": strategy_name,
                        "reason": checklist_reason,
                    })
                    continue

                size_result = strategy_obj.size_position(
                    signal, portfolio_risk, guardrail_status,
                )
                contracts = int(size_result.contracts * regime.options_size_multiplier)
                if contracts <= 0:
                    actions.append({
                        "action": "skipped_zero_size",
                        "strategy": strategy_name,
                    })
                    continue

                order_signal = self._build_order_signal(
                    signal=signal,
                    strategy_name=strategy_name,
                    score=score_result.score,
                    regime=regime,
                    quantity=contracts,
                    expiry=expiry,
                    actual_dte=actual_dte,
                    market=market,
                )

                from app.api.routes.trade_desk import handle_signal
                await handle_signal(order_signal)

                actions.append({
                    "action": "routed",
                    "strategy": strategy_name,
                    "signal_score": score_result.score,
                    "dte": actual_dte,
                    "quantity": contracts,
                })
                portfolio_state.trades_today += 1
                portfolio_risk.open_position_count += 1

        except Exception as exc:
            logger.warning("Options engine scan failed: %s", exc, exc_info=True)
            actions.append({"action": "error", "message": str(exc)})

        return actions

    async def _count_open_positions(self) -> int:
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade
            from sqlalchemy import select, func
            async with AsyncSessionLocal() as session:
                return int((await session.execute(
                    select(func.count()).where(Trade.status == "open")
                )).scalar() or 0)
        except Exception:
            return 0

    async def _load_portfolio_state(self) -> PortfolioState:
        """Reuse trade desk portfolio loader when available."""
        try:
            from app.api.routes.trade_desk import _fetch_portfolio_state
            return await _fetch_portfolio_state()
        except Exception:
            return PortfolioState(
                current_value=settings.starting_capital,
                starting_capital=settings.starting_capital,
                daily_pnl=0,
                weekly_pnl=0,
                monthly_pnl=0,
                consecutive_losses=0,
                trades_today=0,
            )

    async def _load_market_data(self) -> tuple[Optional[float], dict]:
        loop = asyncio.get_running_loop()

        def _fetch():
            return yf.Ticker("SPY").history(period="60d", auto_adjust=True)

        hist = await loop.run_in_executor(None, _fetch)
        if hist is None or len(hist) < 20:
            return None, {}

        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        closes = hist["Close"]
        spy_price = float(closes.iloc[-1])
        rsi = float(self.fetcher.calculate_rsi(closes).iloc[-1])
        sma20 = float(self.fetcher.calculate_sma(closes).iloc[-1])
        rv = float(self.fetcher.calculate_realized_vol(closes).iloc[-1])
        log_rets = np.log(closes / closes.shift()).dropna()
        sigma = float(log_rets.std() * np.sqrt(252)) if len(log_rets) > 5 else rv

        try:
            vix_hist = yf.Ticker("^VIX").history(period="5d")
            vix = float(vix_hist["Close"].iloc[-1]) if len(vix_hist) else sigma * 100
        except Exception:
            vix = sigma * 100

        vix_series = yf.Ticker("^VIX").history(period="60d")
        if len(vix_series) >= 5:
            vix_close = vix_series["Close"]
            vix_now = float(vix_close.iloc[-1])
            iv_rank = (vix_now - float(vix_close.min())) / max(
                float(vix_close.max()) - float(vix_close.min()), 0.01
            ) * 100
        else:
            iv_rank = 30.0

        adx = self._compute_adx(hist)

        return spy_price, {
            "rsi": rsi,
            "adx": adx,
            "above_sma20": spy_price > sma20,
            "vix": vix,
            "iv_rank": iv_rank,
            "iv_percentile": iv_rank,
            "rv": rv,
            "sigma": max(sigma, vix / 100.0),
            "vrp": max(vix / 100.0 - rv, 0.0),
        }

    async def _load_chain(
        self,
        symbol: str,
        expiry: date,
        spot: float,
        sigma: float,
    ) -> Optional[OptionsChain]:
        expiry_str = expiry.isoformat()
        try:
            from app.broker.broker_factory import get_broker
            broker = get_broker()
            chain = await broker.get_options_chain(symbol, expiry_str)
            if chain and (chain.puts or chain.calls):
                return chain
        except Exception as exc:
            logger.debug("Broker chain unavailable, using synthetic: %s", exc)

        return self._synthetic_chain(symbol, expiry, spot, sigma)

    def _synthetic_chain(
        self,
        symbol: str,
        expiry: date,
        spot: float,
        sigma: float,
    ) -> OptionsChain:
        """Build a BS-estimated chain when live quotes are unavailable."""
        today = date.today()
        T = max((expiry - today).days / 365.0, 1 / 365.0)
        puts: list[OptionContract] = []
        calls: list[OptionContract] = []

        for offset in range(-80, 81, 5):
            strike = round(spot + offset)
            if strike <= 0:
                continue
            for opt_type, bucket in (("put", puts), ("call", calls)):
                try:
                    if opt_type == "put":
                        mid = self.pricer.put_price(spot, strike, T, RISK_FREE, sigma)
                        delta = self.pricer.delta(spot, strike, T, RISK_FREE, sigma, "put")
                    else:
                        mid = self.pricer.call_price(spot, strike, T, RISK_FREE, sigma)
                        delta = self.pricer.delta(spot, strike, T, RISK_FREE, sigma, "call")
                except Exception:
                    continue
                spread = max(mid * 0.05, 0.01)
                greeks = Greeks(
                    delta=delta,
                    gamma=0.0,
                    theta=0.0,
                    vega=0.0,
                    implied_vol=sigma,
                )
                contract = OptionContract(
                    symbol=f"{symbol}{expiry.strftime('%y%m%d')}{opt_type[0].upper()}{strike}",
                    underlying=symbol,
                    expiration=expiry,
                    strike=Decimal(str(strike)),
                    option_type=opt_type,
                    bid=Decimal(str(round(max(mid - spread / 2, 0.01), 2))),
                    ask=Decimal(str(round(mid + spread / 2, 2))),
                    last=Decimal(str(round(mid, 2))),
                    volume=1000,
                    open_interest=5000,
                    greeks=greeks,
                )
                bucket.append(contract)

        return OptionsChain(
            underlying=symbol,
            expiration=expiry,
            underlying_price=Decimal(str(round(spot, 2))),
            calls=calls,
            puts=puts,
            fetched_at=datetime.now(timezone.utc),
        )

    def _check_flow_gate(
        self,
        strategy_name: str,
        flow_feats: dict,
        direction: str,
    ) -> tuple[bool, str]:
        """
        Block entries that fight institutional flow when flow data is available.
        Neutral flow (0.5) never blocks.
        """
        sentiment = flow_feats.get("flow_sentiment_score", 0.5)
        bullish_sweeps = flow_feats.get("flow_large_sweep_bullish_count", 0)

        if sentiment == 0.5 and bullish_sweeps == 0:
            return True, ""

        if strategy_name in ("bull_put_spread", "bull_call_debit_spread"):
            if sentiment < 0.30:
                return False, f"flow_bearish_sentiment={sentiment:.2f}"
        if strategy_name == "bear_call_spread":
            if sentiment > 0.70:
                return False, f"flow_bullish_sentiment={sentiment:.2f}"
        if strategy_name == "iron_condor" and (
            sentiment < 0.25 or sentiment > 0.75
        ):
            return False, f"flow_directional={sentiment:.2f}_not_range_bound"

        return True, ""

    def _build_features(
        self,
        signal: Signal,
        market: dict,
        actual_dte: int,
        flow_feats: dict,
    ) -> SignalFeatures:
        spread_width = abs(
            float(signal.short_strike or 0) - float(signal.long_strike or 0)
        ) or 10.0
        short_delta = float(signal.target_delta or 0.20)
        credit_ratio = market.get("credit_to_width", 0.25)

        return SignalFeatures(
            iv_rank=market["iv_rank"],
            iv_percentile=market["iv_percentile"],
            vix_level=market["vix"],
            spy_rsi_14=market["rsi"],
            spy_adx_14=market["adx"],
            spy_trend_direction=1.0 if market["above_sma20"] else -1.0,
            days_to_expiry=float(actual_dte),
            short_strike_delta=short_delta,
            spread_width=spread_width,
            credit_to_width_ratio=credit_ratio,
            earnings_days_away=999.0,
            spy_realized_vol_20d=market["rv"],
            iv_minus_rv=market["vrp"],
        )

    def _build_order_signal(
        self,
        signal: Signal,
        strategy_name: str,
        score: float,
        regime: RegimeState,
        quantity: int,
        expiry: date,
        actual_dte: int,
        market: dict,
    ) -> dict:
        opt_type = "call" if "call" in strategy_name and "put" not in strategy_name else "put"
        if strategy_name == "bear_call_spread":
            opt_type = "call"

        short_strike = float(signal.short_strike or 0)
        long_strike = float(signal.long_strike or 0)
        spread_width = abs(short_strike - long_strike) or 10.0

        T = max(actual_dte / 365.0, 1 / 365.0)
        sigma = market["sigma"]
        spot = market.get("spot", 500.0)

        try:
            if opt_type == "put":
                short_px = self.pricer.put_price(spot, short_strike, T, RISK_FREE, sigma)
                long_px = self.pricer.put_price(spot, long_strike, T, RISK_FREE, sigma)
            else:
                short_px = self.pricer.call_price(spot, short_strike, T, RISK_FREE, sigma)
                long_px = self.pricer.call_price(spot, long_strike, T, RISK_FREE, sigma)
            net_credit = round(max(short_px - long_px, 0.01) * 100, 2)
        except Exception:
            net_credit = round(spread_width * 25, 2)

        return {
            "id": str(uuid.uuid4()),
            "ticker": signal.underlying,
            "asset_type": "options",
            "strategy": strategy_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "action": "SELL_SPREAD",
            "confidence": round(regime.confidence, 4),
            "regime": regime.regime.value,
            "signal_score": score,
            "iv_rank": market["iv_rank"],
            "quantity": quantity,
            "spread": {
                "option_type": opt_type,
                "short_strike": short_strike,
                "long_strike": long_strike,
                "expiration": expiry.isoformat(),
                "dte": actual_dte,
                "net_credit": net_credit,
                "max_loss": round((spread_width - net_credit / 100) * 100 * quantity, 2),
                "breakeven": (
                    round(short_strike - net_credit / 100, 2)
                    if opt_type == "put"
                    else round(short_strike + net_credit / 100, 2)
                ),
            },
        }

    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        try:
            from ml.features import compute_adx
            adx_series = compute_adx(df["High"], df["Low"], df["Close"], period)
            val = adx_series.iloc[-1]
            return float(val) if not pd.isna(val) else 15.0
        except Exception:
            return 15.0


options_engine = OptionsEngine()
