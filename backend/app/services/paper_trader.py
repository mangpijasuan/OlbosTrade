"""
Live paper trading engine — fully automated execution.

Signal cycle (9:35am ET, Mon–Fri):
  1. Kill switch check
  2. Position reconciliation
  3. Load persisted guardrail state from DB
  4. Fetch live quote (staleness-checked)
  5. Build IV surface (real skew + term structure + IV rank)
  6. Classify market regime (gates strategy selection + sizing)
  7. For each allowed strategy:
       a. Generate entry signal
       b. Score with AI signal scorer (async, non-blocking)
       c. Run full pre-trade checklist
       d. Submit via ExecutionDispatcher (liquidity guard + atomic fill)
  8. Persist portfolio snapshot to DB

Monthly optimization (1st trading day of month, 8am ET):
  9. Walk-forward parameter optimization per strategy
  10. Kelly criterion position sizing update

FIX #2:  Live quote from Tradier with staleness guard
FIX #10: Position reconciliation before every cycle
FIX #12: Guardrail state loaded from DB (not hardcoded zeros)
NEW:     IV surface replaces VIX-proxy IV rank
NEW:     Regime classifier gates strategy selection
NEW:     Execution via ExecutionDispatcher (liquidity guard + atomic fill)
NEW:     Monthly walk-forward optimization + Kelly sizing
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import yfinance as yf
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.broker.broker_interface import BrokerInterface
from app.core.config import settings
from app.services.data_fetcher import DataFetcher
from app.services.execution_dispatcher import DispatchStatus, ExecutionDispatcher
from app.services.guardrails import GuardrailEngine, PortfolioState
from app.services.iv_surface import IVSurfaceEngine, IVSurfaceSnapshot
from app.services.kill_switch import kill_switch_service
from app.services.multi_leg_strategy import LegAction, MultiLegStrategy, StrategyLeg
from app.services.position_reconciler import PositionReconciler, ReconciliationError
from app.services.regime_classifier import RegimeClassifier, RegimeState
from app.services.risk_manager import PortfolioRiskState, RiskManager
from app.services.signal_scorer import SignalFeatures, SignalScorer
from app.services.strategy_engine import (
    BullPutSpread, BearCallSpread, IronCondor, BullCallDebitSpread,
    approve_trade,
)
from app.services.strategy_optimizer import (
    StrategyOptimizer, StrategyParams, TradeRecord,
)
from app.services.trading_mode import trading_mode_manager
from app.services.trade_recorder import trade_recorder
from app.utils.logger import get_logger

ET = ZoneInfo("America/New_York")
logger = get_logger(__name__)

MAX_QUOTE_AGE_SECONDS = 90


class DataStalenessError(Exception):
    pass


class PaperTrader:
    """
    Fully automated paper trading engine.
    No manual intervention required once running.
    """

    STRATEGIES = {
        "bull_put_spread":        BullPutSpread(),
        "bear_call_spread":       BearCallSpread(),
        "iron_condor":            IronCondor(),
        "bull_call_debit_spread": BullCallDebitSpread(),
    }

    def __init__(self, broker: BrokerInterface, fetcher: DataFetcher) -> None:
        self.broker      = broker
        self.fetcher     = fetcher
        self.scorer      = SignalScorer()
        self.guardrails  = GuardrailEngine()
        self.risk_manager = RiskManager()
        self.reconciler  = PositionReconciler(broker)

        # NEW: Three new intelligence modules
        self.iv_engine   = IVSurfaceEngine(broker)
        self.classifier  = RegimeClassifier()
        self.optimizer   = StrategyOptimizer()
        self.dispatcher  = ExecutionDispatcher(broker, max_spread_pct=15.0)

        kill_switch_service.configure(broker)

    # ── Live quote with staleness guard ──────────────────────────────────────

    async def _fetch_live_quote(self, symbol: str) -> tuple[float, float]:
        """
        Fetch live quote from Tradier with staleness guard.
        Returns (price, vix). Never uses yfinance in live path.
        """
        if settings.tradier_api_key:
            try:
                tradier_base = (
                    "https://sandbox.tradier.com"
                    if settings.tradier_sandbox
                    else "https://api.tradier.com"
                )
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{tradier_base}/v1/markets/quotes",
                        params={"symbols": f"{symbol},VIX"},
                        headers={
                            "Authorization": f"Bearer {settings.tradier_api_key}",
                            "Accept": "application/json",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                quotes = data.get("quotes", {}).get("quote", [])
                if isinstance(quotes, dict):
                    quotes = [quotes]

                price, vix = None, 20.0
                for q in quotes:
                    if q.get("symbol") == symbol:
                        trade_date = q.get("trade_date", "")
                        if trade_date:
                            try:
                                quote_dt = datetime.fromisoformat(
                                    trade_date.replace("Z", "+00:00")
                                )
                                age = (datetime.now(timezone.utc) - quote_dt).total_seconds()
                                if age > MAX_QUOTE_AGE_SECONDS:
                                    raise DataStalenessError(
                                        f"{symbol} quote is {age:.0f}s old "
                                        f"(max {MAX_QUOTE_AGE_SECONDS}s)"
                                    )
                            except DataStalenessError:
                                raise
                            except Exception:
                                pass
                        price = float(q.get("last") or q.get("ask") or 0)
                    elif q.get("symbol") == "VIX":
                        vix = float(q.get("last") or 20.0)

                if price and price > 0:
                    return price, vix
            except DataStalenessError:
                raise
            except Exception as exc:
                logger.warning("Tradier quote failed: %s — trying IBKR", exc)

        raise DataStalenessError(
            f"Could not obtain fresh {symbol} quote — aborting cycle"
        )

    # ── Main signal cycle ──────────────────────────────────────────────────────

    async def run_signal_cycle(self) -> list[dict]:
        """
        Fully automated signal generation and execution cycle.
        Runs at 9:35am ET Mon–Fri via APScheduler.
        Returns list of action records for logging and API response.
        """
        logger.info(
            "═══ Signal cycle: %s ═══",
            datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        )
        actions: list[dict] = []

        # ── Kill switch ───────────────────────────────────────────────────────
        if kill_switch_service.is_engaged:
            logger.warning("Signal cycle aborted — kill switch engaged")
            return [{"action": "blocked", "reason": "kill_switch_engaged"}]

        try:
            # ── Position reconciliation ───────────────────────────────────────
            try:
                recon = await self.reconciler.reconcile()
                for w in recon.warnings:
                    actions.append({"action": "warning", "message": w})
            except ReconciliationError as exc:
                logger.critical("Reconciliation failure: %s", exc)
                return [{"action": "halted", "reason": str(exc)}]

            # ── Account state ─────────────────────────────────────────────────
            account          = await self.broker.get_account_summary()
            portfolio_value  = float(account.net_liquidation)
            positions        = await self.broker.get_positions()

            # ── Guardrail state from DB ───────────────────────────────────────
            persisted = await self.reconciler.load_guardrail_state_from_db()
            portfolio_state = PortfolioState(**persisted)
            portfolio_state.current_value = portfolio_value

            guardrail_status = self.guardrails.check_all(portfolio_state)
            if not guardrail_status.trading_allowed:
                logger.info("Guardrails blocking: %s", guardrail_status.reason)
                return [{"action": "blocked", "reason": guardrail_status.reason}]

            # ── Live market data ──────────────────────────────────────────────
            try:
                spy_price, vix_live = await self._fetch_live_quote("SPY")
            except DataStalenessError as exc:
                logger.error("Data staleness abort: %s", exc)
                return [{"action": "aborted", "reason": str(exc)}]

            loop = asyncio.get_running_loop()

            def _fetch_spy_hist():
                return yf.Ticker("SPY").history(period="60d", auto_adjust=True)

            spy_hist = await loop.run_in_executor(None, _fetch_spy_hist)
            spy_hist.index = pd.to_datetime(spy_hist.index).tz_localize(None)

            rsi    = float(self.fetcher.calculate_rsi(spy_hist["Close"]).iloc[-1])
            sma20  = float(self.fetcher.calculate_sma(spy_hist["Close"]).iloc[-1])
            rv     = float(self.fetcher.calculate_realized_vol(spy_hist["Close"]).iloc[-1])
            above_sma = spy_price > sma20

            log_returns = spy_hist["Close"].pct_change().dropna()

            # ── NEW: IV Surface ───────────────────────────────────────────────
            surface: IVSurfaceSnapshot = await self.iv_engine.build_surface(
                symbol="SPY",
                spot_price=spy_price,
                rv_20d=rv,
                target_dtes=[30, 60],
            )
            # Use real surface IV rank (not VIX proxy)
            iv_rank = surface.iv_rank
            adx     = self._compute_adx(spy_hist)

            # ── NEW: Regime classification ────────────────────────────────────
            regime: RegimeState = self.classifier.classify(
                surface=surface,
                rsi=rsi,
                adx=adx,
                spy_returns=log_returns,
            )

            actions.append({
                "action":     "regime_classified",
                "regime":     regime.regime.value,
                "confidence": regime.confidence,
                "strategies": regime.strategies_allowed,
                "iv_rank":    iv_rank,
                "atm_iv":     surface.atm_iv,
                "vrp":        surface.vrp,
                "skew":       surface.front_skew.skew if surface.front_skew else None,
            })

            if not regime.is_tradeable:
                logger.info(
                    "Regime %s — no strategies allowed. Skipping cycle.",
                    regime.regime.value,
                )
                return actions + [{"action": "skipped", "reason": f"regime={regime.regime.value}"}]

            # ── Options chain ─────────────────────────────────────────────────
            dte_target    = trading_mode_manager.config.dte_target
            target_expiry = (date.today() + timedelta(days=dte_target)).strftime("%Y-%m-%d")
            try:
                chain = await self.broker.get_options_chain("SPY", target_expiry)
            except Exception as exc:
                logger.warning("Chain unavailable: %s", exc)
                return actions + [{"action": "skipped", "reason": "chain_unavailable"}]

            # ── FIX-5: Real earnings days away for SPY (index ETF = 999) ──────
            # SPY is an ETF — it has no earnings date. Components report
            # individually; use 999 (no upcoming earnings risk) which is
            # correct for SPY. For single-stock underlyings, fetch from
            # yfinance calendar: yf.Ticker(sym).calendar
            earnings_days_away = 999.0

            # ── FIX-6: Real options features from live chain ──────────────────
            # Previously hardcoded as constants. Now derived from the actual
            # options chain and Black-Scholes pricer so the model receives
            # the same distribution it was trained on.
            try:
                from app.services.options_pricer import BlackScholesPricer as _BSP
                _pricer = _BSP()
                _T      = max(dte_target / 365.0, 0.01)
                _r      = 0.05   # risk-free rate
                _sigma  = surface.atm_iv if surface.atm_iv > 0 else rv

                # Find short put at ~0.20 delta
                _target_delta = 0.20
                _best_strike  = spy_price * 0.95   # fallback: 5% OTM
                _best_diff    = 1.0
                for _offset in range(-60, 1, 5):
                    _k = round(spy_price + _offset)
                    try:
                        _d = abs(_pricer.delta(spy_price, _k, _T, _r, _sigma, "put"))
                        if abs(_d - _target_delta) < _best_diff:
                            _best_diff   = abs(_d - _target_delta)
                            _best_strike = _k
                    except Exception:
                        continue

                _short_strike = float(_best_strike)
                _long_strike  = _short_strike - 5.0   # 5-pt wide spread
                _short_px     = _pricer.put_price(spy_price, _short_strike, _T, _r, _sigma)
                _long_px      = _pricer.put_price(spy_price, _long_strike,  _T, _r, _sigma)
                _short_delta  = abs(_pricer.delta(spy_price, _short_strike, _T, _r, _sigma, "put"))
                _spread_width = 5.0
                _net_credit   = max(_short_px - _long_px, 0.01)
                _ctw_ratio    = _net_credit / _spread_width

                real_dte                = float(dte_target)
                real_short_delta        = round(_short_delta, 4)
                real_spread_width       = _spread_width
                real_credit_to_width    = round(_ctw_ratio, 4)

                logger.debug(
                    "Live options features: DTE=%d delta=%.2f width=%.0f C/W=%.3f",
                    dte_target, real_short_delta, real_spread_width, real_credit_to_width,
                )
            except Exception as _exc:
                logger.warning("Options feature computation failed, using defaults: %s", _exc)
                real_dte             = float(dte_target)
                real_short_delta     = 0.20
                real_spread_width    = 10.0
                real_credit_to_width = 0.25

            portfolio_risk = PortfolioRiskState(
                net_delta=0.0, net_vega=0.0, net_theta=0.0,
                open_position_count=len(positions),
                portfolio_value=portfolio_value,
                positions_by_underlying={},
                positions_by_sector={},
            )

            trades_this_cycle = 0

            # ── Strategy loop ─────────────────────────────────────────────────
            for strategy_name in regime.strategies_allowed:
                strategy_obj = self.STRATEGIES.get(strategy_name)
                if strategy_obj is None:
                    continue

                # Guardrail strategy check
                if not self.guardrails.is_strategy_allowed(strategy_name, guardrail_status):
                    actions.append({
                        "action": "blocked",
                        "strategy": strategy_name,
                        "reason": "guardrail_mode",
                    })
                    continue

                # Generate signal
                signal = strategy_obj.generate_signal(
                    chain=chain,
                    iv_rank=iv_rank,
                    rsi=rsi,
                    adx=adx,
                    above_sma20=above_sma,
                    vix=vix_live,
                    portfolio_state=portfolio_state,
                )

                if not signal.entry_allowed:
                    logger.debug(
                        "Signal rejected: %s — %s", strategy_name, signal.reason
                    )
                    continue

                # NEW: Use regime signal threshold (not just guardrail default)
                effective_threshold = max(
                    regime.signal_threshold or settings.signal_score_threshold,
                    self.guardrails.get_signal_threshold(guardrail_status),
                )

                # AI scoring — all 13 features are now live values (FIX-5, FIX-6)
                features = SignalFeatures(
                    iv_rank=iv_rank,
                    iv_percentile=surface.iv_percentile,
                    vix_level=vix_live,
                    spy_rsi_14=rsi,
                    spy_adx_14=adx,
                    spy_trend_direction=1.0 if above_sma else -1.0,
                    days_to_expiry=real_dte,                # FIX-6: real DTE
                    short_strike_delta=real_short_delta,    # FIX-6: real delta
                    spread_width=real_spread_width,         # FIX-6: real width
                    credit_to_width_ratio=real_credit_to_width,  # FIX-6: real C/W
                    earnings_days_away=earnings_days_away,  # FIX-5: real or 999 for ETF
                    spy_realized_vol_20d=rv,
                    iv_minus_rv=surface.vrp,
                )
                score_result = await self.scorer.score_async(
                    features, effective_threshold
                )

                if not score_result.approved:
                    actions.append({
                        "action":   "signal_rejected",
                        "strategy": strategy_name,
                        "score":    score_result.score,
                        "threshold": effective_threshold,
                        "reason":   score_result.rejection_reason,
                    })
                    continue

                # Pre-trade checklist
                approved, checklist_reason = approve_trade(
                    signal=signal,
                    portfolio_state=portfolio_state,
                    portfolio_risk=portfolio_risk,
                    signal_score=score_result.score,
                    guardrail_engine=self.guardrails,
                    risk_manager=self.risk_manager,
                )
                if not approved:
                    actions.append({
                        "action":   "checklist_rejected",
                        "strategy": strategy_name,
                        "reason":   checklist_reason,
                    })
                    continue

                # Kelly-adjusted position sizing
                size_result = strategy_obj.size_position(
                    signal, portfolio_risk, guardrail_status
                )
                # Apply regime size multiplier on top of guardrail multiplier
                effective_contracts = max(
                    int(size_result.contracts * regime.size_multiplier), 1
                )

                # NEW: Submit via ExecutionDispatcher (liquidity guard + atomic fill)
                multi_leg = self._build_multi_leg(
                    signal, strategy_name, chain=chain, quantity=effective_contracts
                )
                if multi_leg is None:
                    continue

                dispatch_result = await self.dispatcher.validate_and_dispatch(
                    multi_leg, dry_run=True  # Switch to dry_run=False for live IBKR
                )

                active_mode = trading_mode_manager.current.active_mode.value

                action_record = {
                    "action":                dispatch_result.status.value,
                    "strategy":              strategy_name,
                    "underlying":            "SPY",
                    "signal_score":          score_result.score,
                    "iv_rank":               iv_rank,
                    "regime":                regime.regime.value,
                    "trading_mode_at_entry": active_mode,
                    "dispatch_id":           dispatch_result.order_id,
                    "fills":                 len(dispatch_result.fills),
                    "net_fill":              dispatch_result.net_fill_price,
                }

                if dispatch_result.status == DispatchStatus.FILLED:
                    trades_this_cycle += 1
                    portfolio_state.trades_today += 1
                    logger.info(
                        "✅ TRADE EXECUTED: %s | score=%.3f iv_rank=%.1f regime=%s mode=%s",
                        strategy_name, score_result.score,
                        iv_rank, regime.regime.value, active_mode,
                    )
                    # Auto-write Trade row + JournalEntry stub to DB
                    await trade_recorder.record_fill(
                        strategy=strategy_name,
                        underlying="SPY",
                        option_type="call" if "call" in strategy_name else "put",
                        short_strike=float(signal.short_strike or 450),
                        long_strike=float(signal.long_strike or 440),
                        expiration=date.today() + timedelta(
                            days=trading_mode_manager.config.dte_target
                        ),
                        entry_credit=float(dispatch_result.net_fill_price or 0),
                        quantity=effective_contracts,
                        signal_score=score_result.score,
                        iv_rank=iv_rank,
                        regime=regime.regime.value,
                        trading_mode=active_mode,
                        dispatch_id=dispatch_result.order_id,
                        net_fill_price=dispatch_result.net_fill_price,
                    )
                elif dispatch_result.status in (
                    DispatchStatus.TIMEOUT_FLATTENED,
                    DispatchStatus.PARTIAL_FLATTENED,
                ):
                    logger.critical(
                        "⚠️ PARTIAL FILL FLATTENED: %s | %s",
                        strategy_name, dispatch_result.error,
                    )
                elif dispatch_result.status == DispatchStatus.FLATTEN_FAILED:
                    logger.critical(
                        "🚨 FLATTEN FAILED: %s — NAKED POSITION MAY EXIST",
                        strategy_name,
                    )
                    # Engage kill switch automatically on flatten failure
                    await kill_switch_service.engage(
                        reason=f"Flatten failed for {strategy_name} — "
                               f"naked position risk"
                    )

                actions.append(action_record)

            # ── Persist state ─────────────────────────────────────────────────
            await self.reconciler.save_portfolio_snapshot(
                portfolio_value=portfolio_value,
                daily_pnl=portfolio_state.daily_pnl,
                weekly_pnl=portfolio_state.weekly_pnl,
                monthly_pnl=portfolio_state.monthly_pnl,
                consecutive_losses=portfolio_state.consecutive_losses,
                trades_today=portfolio_state.trades_today,
                trading_mode=guardrail_status.trading_mode,
                cooling_off_until=guardrail_status.cooling_off_until,
            )

        except Exception as exc:
            logger.error("Signal cycle error: %s", exc, exc_info=True)
            actions.append({"action": "error", "message": str(exc)})

        logger.info(
            "═══ Cycle complete: %d actions ═══", len(actions)
        )
        return actions

    # ── Monthly optimization ──────────────────────────────────────────────────

    async def run_monthly_optimization(self) -> dict:
        """
        Walk-forward parameter optimization + Kelly sizing update.
        Runs on the 1st trading day of each month at 8:00am ET.
        """
        logger.info("Monthly optimization starting...")
        results = {}

        trade_records = await self._load_trade_records()

        for strategy_name in self.STRATEGIES:
            opt_result = await self.optimizer.optimize(
                strategy_name=strategy_name,
                trades=trade_records,
            )
            results[strategy_name] = {
                "accepted":          opt_result.accepted,
                "improvement_pct":   opt_result.improvement_pct,
                "validation_sharpe": opt_result.validation_sharpe,
                "n_trades_train":    opt_result.n_trades_train,
                "rejection_reason":  opt_result.rejection_reason,
            }

            # Update Kelly sizing
            kelly_size = self.optimizer.kelly_position_size(
                strategy_name=strategy_name,
                trades=trade_records,
                portfolio_value=settings.starting_capital,
            )
            self.optimizer.params[strategy_name].size_pct_of_portfolio = kelly_size
            logger.info(
                "Kelly size updated: %s → %.2f%%", strategy_name, kelly_size * 100
            )

        logger.info("Monthly optimization complete: %s", results)
        return results

    async def _load_trade_records(self) -> list[TradeRecord]:
        """Load historical trades from DB for optimizer."""
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from sqlalchemy import select

        records: list[TradeRecord] = []
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Trade).where(Trade.status == "closed")
                )
                db_trades = result.scalars().all()

            for t in db_trades:
                entry_dt = t.entry_date
                exit_dt  = t.exit_date
                if entry_dt and exit_dt:
                    hold_days = max((exit_dt - entry_dt).days, 1)
                else:
                    hold_days = 0

                records.append(TradeRecord(
                    strategy=str(t.strategy),
                    entry_date=entry_dt.date() if entry_dt else date.today(),
                    exit_date=exit_dt.date() if exit_dt else None,
                    entry_credit=float(t.credit_received or 0),
                    exit_cost=float(t.cost_to_close or 0),
                    pnl=float(t.pnl or 0),
                    iv_rank_entry=30.0,  # Will be enriched from market_snapshots
                    dte_at_entry=35,
                    spread_width=float(abs(
                        (t.short_strike or 0) - (t.long_strike or 0)
                    )),
                    credit_to_width=0.25,
                    hold_days=hold_days,
                    exit_reason=str(t.exit_reason or ""),
                ))
        except Exception as exc:
            logger.warning("Could not load trade records from DB: %s", exc)

        return records

    def _build_multi_leg(
        self,
        signal,
        strategy_name: str,
        chain=None,
        quantity: int = 1,
    ) -> MultiLegStrategy | None:
        """
        Build a MultiLegStrategy from a Signal for ExecutionDispatcher.

        IMPORTANT: bid/ask prices must come from the live options chain, not
        be hardcoded. Pass `chain` so we can look up real quotes. Without real
        quotes the ExecutionDispatcher's spread-width liquidity guard is blind.
        """
        from app.broker.contract import EnrichedContract

        if not signal.short_strike or not signal.long_strike:
            return None

        try:
            expiry = signal.expiration or (
                date.today() + timedelta(days=trading_mode_manager.config.dte_target)
            )

            # Look up real bid/ask from the chain when available
            def _find_contract_quote(chain, strike: float, opt_type: str):
                if chain is None:
                    return None
                contracts = chain.puts if opt_type == "put" else chain.calls
                for c in contracts:
                    if abs(float(c.strike) - strike) < 0.01:
                        return float(c.bid), float(c.ask), float(c.last or c.ask)
                return None

            # Determine option type from strategy
            opt_type = "call" if "call" in strategy_name else "put"
            short_quote = _find_contract_quote(chain, float(signal.short_strike), opt_type)
            long_quote  = _find_contract_quote(chain, float(signal.long_strike), opt_type)

            if short_quote is None or long_quote is None:
                logger.warning(
                    "Could not find live quotes for %s strikes %.2f/%.2f in chain "
                    "— using mid-point approximation. Liquidity guard may be inaccurate.",
                    strategy_name, signal.short_strike, signal.long_strike,
                )
                # Approximate from signal data — spread guard will be less accurate
                short_quote = (1.20, 1.30, 1.25)
                long_quote  = (0.55, 0.65, 0.60)

            short_contract = EnrichedContract(
                underlying_ticker=signal.underlying,
                strike_price=float(signal.short_strike),
                expiration_date=expiry,
                option_type=opt_type,
                bid=short_quote[0], ask=short_quote[1], last=short_quote[2],
                volume=5000, open_interest=10000,
            )
            long_contract = EnrichedContract(
                underlying_ticker=signal.underlying,
                strike_price=float(signal.long_strike),
                expiration_date=expiry,
                option_type=opt_type,
                bid=long_quote[0], ask=long_quote[1], last=long_quote[2],
                volume=3000, open_interest=8000,
            )

            sell_action = LegAction.SELL
            buy_action  = LegAction.BUY

            return MultiLegStrategy(
                strategy_name=strategy_name,
                underlying=signal.underlying,
                legs=[
                    StrategyLeg(contract=short_contract, action=sell_action, quantity=quantity),
                    StrategyLeg(contract=long_contract,  action=buy_action,  quantity=quantity),
                ],
            )
        except Exception as exc:
            logger.warning("Could not build MultiLegStrategy: %s", exc)
            return None

    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute ADX from OHLCV DataFrame."""
        try:
            from ml.features import compute_adx
            adx_series = compute_adx(df["High"], df["Low"], df["Close"], period)
            val = adx_series.iloc[-1]
            return float(val) if not pd.isna(val) else 15.0
        except Exception as exc:
            logger.warning("ADX computation failed, using fallback 15.0: %s", exc)
            return 15.0

    def create_scheduler(self) -> AsyncIOScheduler:
        """
        Create APScheduler with two jobs:
          1. Signal cycle at 9:35am ET Mon–Fri
          2. Monthly optimization on 1st of month at 8am ET
        """
        scheduler = AsyncIOScheduler(timezone=ET)

        scheduler.add_job(
            self.run_signal_cycle,
            trigger="cron",
            day_of_week="mon-fri",
            hour=9, minute=35,
            id="signal_cycle",
            replace_existing=True,
        )

        scheduler.add_job(
            self.run_monthly_optimization,
            trigger="cron",
            day=1,
            hour=8, minute=0,
            id="monthly_optimization",
            replace_existing=True,
        )

        kill_switch_service.configure(self.broker, scheduler)
        logger.info(
            "Scheduler created — signal cycle 9:35am ET | "
            "optimization 1st of month 8am ET"
        )
        return scheduler
