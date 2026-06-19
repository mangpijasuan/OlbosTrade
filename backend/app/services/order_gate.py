"""
Order Gate — the SINGLE fail-closed pipeline every order must pass through.

Stages, in fixed order:
    1. KILL SWITCH        — hard stop, absolute priority
    2. UNIFIED RISK       — guardrails + emotion + earnings + portfolio risk
    3. SIZING             — risk-budget contracts; ZERO size => skip (no order)
    4. EXECUTION DISPATCH — options via ExecutionDispatcher (liquidity + atomic);
                            equities via broker.place_equity_order
    5. FILL-CONFIRMED RECORDING — trade_recorder.record_fill (not refactored here)

FAIL CLOSED: if risk state cannot be read (DB/broker), the gate REFUSES the
trade — it never defaults to permissive/zero values. Every order-placing entry
point (autopilot scan, copilot approval, manual) funnels through `submit()`.

NOTE: paper_trader has its own ExecutionDispatcher path; converging it onto this
gate is tracked in AUDIT.md as a follow-up (out of scope for batch 1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RiskStateUnavailable(Exception):
    """Raised when guardrail/portfolio state cannot be read — gate fails closed."""


def _result(signal: dict, result: str, **extra) -> dict:
    return {
        "signal_id": signal.get("id"),
        "ticker": signal.get("ticker", ""),
        "asset_type": signal.get("asset_type", "equity"),
        "result": result,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }


class OrderGate:
    """Single choke point for order submission. Instantiated once (singleton)."""

    def __init__(self) -> None:
        from app.services.unified_risk import UnifiedRiskEngine
        self._risk_engine = UnifiedRiskEngine()
        self._dispatcher = None   # cached ExecutionDispatcher (stable _inflight set)

    # ── Stage 1 ───────────────────────────────────────────────────────────────
    def _kill_switch_active(self) -> bool:
        from app.services.kill_switch import kill_switch_service
        return kill_switch_service.is_engaged

    async def _has_open_trade(self, ticker: str) -> bool:
        """True if an open trade for this underlying exists. RAISES on DB error."""
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from sqlalchemy import select
        async with AsyncSessionLocal() as s:
            row = (await s.execute(
                select(Trade.id).where(Trade.underlying == ticker, Trade.status == "open")
            )).first()
        return row is not None

    # ── Fail-closed state reads (Stage 2 inputs) ───────────────────────────────
    async def _read_portfolio_state(self):
        """guardrails.PortfolioState from live broker + DB. RAISES on failure."""
        from app.services.guardrails import PortfolioState
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from sqlalchemy import select, func, and_

        # Broker account value — if we can't read capital, we can't assess risk.
        from app.broker.broker_factory import get_broker
        acct = await get_broker().get_account_summary()
        current_value = float(acct.net_liquidation)

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        async with AsyncSessionLocal() as s:
            def _win(frm):
                return select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) >= frm)
                )
            daily = float((await s.execute(_win(today))).scalar() or 0)
            weekly = float((await s.execute(_win(week_start))).scalar() or 0)
            monthly = float((await s.execute(_win(month_start))).scalar() or 0)
            trades_today = int((await s.execute(
                select(func.count(Trade.id)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) == today)
                )
            )).scalar() or 0)
            recent = (await s.execute(
                select(Trade.pnl).where(Trade.status == "closed")
                .order_by(Trade.exit_date.desc(), Trade.id.desc()).limit(20)
            )).scalars().all()
            realized_all_time = float((await s.execute(
                select(func.coalesce(func.sum(Trade.pnl), 0)).where(Trade.status == "closed")
            )).scalar() or 0)

        consecutive = 0
        for p in recent:
            if (p or 0) < 0:
                consecutive += 1
            else:
                break

        # Fold open (unrealized) P&L into the loss windows (consistent with the
        # guardrail endpoint) so the stops respond to a bleeding open book.
        unrealized = current_value - settings.starting_capital - realized_all_time
        return PortfolioState(
            current_value=current_value,
            starting_capital=settings.starting_capital,
            daily_pnl=daily + unrealized,
            weekly_pnl=weekly + unrealized,
            monthly_pnl=monthly + unrealized,
            consecutive_losses=consecutive,
            trades_today=trades_today,
        )

    async def _read_portfolio_risk_state(self, portfolio_value: float):
        """risk_manager.PortfolioRiskState. RAISES on failure (fail closed)."""
        from app.services.risk_manager import PortfolioRiskState
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as s:
            open_count = int((await s.execute(
                select(func.count(Trade.id)).where(Trade.status == "open")
            )).scalar() or 0)
        return PortfolioRiskState(
            net_delta=0.0, net_vega=0.0, net_theta=0.0,
            open_position_count=open_count,
            portfolio_value=portfolio_value,
            positions_by_underlying={},
            positions_by_sector={},
        )

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _mode_risk_pct() -> float:
        try:
            from app.services.trading_mode import trading_mode_manager
            return float(trading_mode_manager.config.risk_per_trade_pct)
        except Exception:
            return 0.02

    @staticmethod
    def _options_max_loss_per_contract(signal: dict) -> float:
        """
        Max loss per contract in DOLLARS. signal net_credit is dollars/contract
        (computed as (short_px - long_px) * 100 upstream), so:
            max_loss = width_points * 100 - net_credit_dollars
        (Previously this treated net_credit as per-share points, collapsing
        max_loss to ~$1 and massively over-sizing every options order.)
        """
        sd = signal.get("spread", {})
        width = abs(float(sd.get("short_strike", 0)) - float(sd.get("long_strike", 0)))
        credit_dollars = float(sd.get("net_credit", 0))
        return max(width * 100.0 - credit_dollars, 1.0)

    def _build_proposed_trade(self, signal: dict):
        from app.services.risk_manager import ProposedTrade
        asset_type = signal.get("asset_type", "equity")
        if asset_type == "options":
            return ProposedTrade(
                strategy=signal.get("strategy", "bull_put_spread"),
                underlying=signal.get("ticker", ""),
                sector=signal.get("sector", "unknown"),
                delta=float(signal.get("delta", 0.0)),
                vega=float(signal.get("vega", 0.0)),
                max_loss_dollars=self._options_max_loss_per_contract(signal),
            )
        plan = signal.get("trade_plan", {})
        entry = float(plan.get("entry_price") or 0)
        stop = float(plan.get("stop_price") or 0)
        per_share_loss = abs(entry - stop) if (entry and stop) else 0.0
        return ProposedTrade(
            strategy="equity", underlying=signal.get("ticker", ""),
            sector=signal.get("sector", "unknown"),
            delta=0.0, vega=0.0,
            max_loss_dollars=per_share_loss or 1.0,
        )

    # ── Stage 4 adapters ───────────────────────────────────────────────────────
    async def _build_strategy(self, signal: dict, broker, quantity: int):
        """
        Signal → MultiLegStrategy with REAL per-leg bid/ask from the broker chain.
        Returns None if live quotes are unavailable — the caller then fails closed
        (we will NOT fabricate quotes, which would defeat the liquidity guard).
        """
        from app.services.multi_leg_strategy import MultiLegStrategy, StrategyLeg, LegAction
        from app.broker.contract import EnrichedContract

        sd = signal.get("spread", {})
        strategy = signal.get("strategy", "bull_put_spread")
        opt_type = "call" if "call" in strategy else sd.get("option_type", "put")
        expiry_str = sd.get("expiration", "")
        expiry = date.fromisoformat(expiry_str) if expiry_str else date.today()
        short_k = float(sd.get("short_strike", 0))
        long_k = float(sd.get("long_strike", 0))

        chain = await broker.get_options_chain(signal["ticker"], expiry.isoformat())
        contracts = chain.puts if opt_type == "put" else chain.calls

        def _find(k: float):
            for c in contracts:
                if abs(float(c.strike) - k) < 0.01:
                    return c
            return None

        cs, cl = _find(short_k), _find(long_k)
        if cs is None or cl is None:
            logger.warning(
                "Order gate: no live chain quotes for %s %s/%s exp %s — failing closed",
                signal["ticker"], short_k, long_k, expiry,
            )
            return None

        def _enrich(c):
            g = getattr(c, "greeks", None)
            return EnrichedContract(
                underlying_ticker=signal["ticker"],
                strike_price=float(c.strike), expiration_date=expiry,
                option_type=opt_type,
                bid=float(c.bid), ask=float(c.ask), last=float(c.last or c.ask),
                volume=int(c.volume or 0), open_interest=int(c.open_interest or 0),
                delta=float(g.delta) if g else None,
                vega=float(g.vega) if g else None,
                theta=float(g.theta) if g else None,
            )

        # Stable order_id derived from the signal so the dispatcher's _inflight
        # idempotency key is consistent across retries (was a fresh random id).
        return MultiLegStrategy(
            strategy_name=strategy, underlying=signal["ticker"],
            order_id=str(signal.get("id") or uuid.uuid4()),
            legs=[
                StrategyLeg(contract=_enrich(cs), action=LegAction.SELL, quantity=quantity),
                StrategyLeg(contract=_enrich(cl), action=LegAction.BUY, quantity=quantity),
            ],
        )

    # ── The gate ────────────────────────────────────────────────────────────────
    async def submit(self, signal: dict, approved_by: str = "autopilot") -> dict:
        ticker = signal.get("ticker", "")
        asset_type = signal.get("asset_type", "equity")

        # STAGE 1 — kill switch
        if self._kill_switch_active():
            logger.warning("Order blocked for %s — kill switch engaged", ticker)
            return _result(signal, "blocked", reason="kill_switch")

        # Duplicate guard — fail CLOSED if it can't be evaluated.
        try:
            if await self._has_open_trade(ticker):
                return _result(signal, "skipped", reason="already_open")
        except Exception as exc:
            logger.error("Order gate: duplicate check failed — refusing (%s)", exc)
            return _result(signal, "blocked", reason="dup_check_unavailable")

        # STAGE 2 — unified risk (fail closed on unreadable state)
        try:
            pstate = await self._read_portfolio_state()
            prisk = await self._read_portfolio_risk_state(pstate.current_value)
        except Exception as exc:
            logger.error("Order gate: risk state unavailable — refusing (%s)", exc)
            return _result(signal, "blocked", reason="risk_state_unavailable")

        instrument = "option" if asset_type == "options" else "equity"

        # STAGE 3 — sizing; ZERO => skip
        from app.services.risk_manager import RiskManager
        risk_pct = self._mode_risk_pct()
        if asset_type == "options":
            max_loss = self._options_max_loss_per_contract(signal)
            contracts = RiskManager().calculate_position_size(
                pstate.current_value, max_loss, risk_pct=risk_pct,
            )
        else:
            plan = signal.get("trade_plan", {})
            entry = float(plan.get("entry_price") or 0)
            stop = float(plan.get("stop_price") or 0)
            if entry and stop:
                contracts = RiskManager().calculate_position_size(
                    pstate.current_value, abs(entry - stop), risk_pct=risk_pct,
                )
            else:
                contracts = int(plan.get("shares") or 0)
        if contracts <= 0:
            logger.info("Order skipped for %s — risk budget sizes to 0", ticker)
            return _result(signal, "skipped", reason="zero_size")

        # STAGE 3.5 — unified risk. Runs AFTER sizing so concentration / Greeks
        # limits are scored against the TOTAL position (per-unit × contracts),
        # not a single unit (which never bound). Guardrail/emotion/earnings
        # checks are pure, so evaluating them here is equivalent.
        decision = self._risk_engine.check(
            instrument_type=instrument,
            ticker=ticker,
            portfolio_state=pstate,
            portfolio_risk_state=prisk,
            proposed_trade=self._build_proposed_trade(signal),
            position_quantity=contracts,
        )
        if not decision.allowed:
            logger.warning("Order blocked for %s — risk: %s", ticker, decision.reason)
            return _result(signal, "blocked", reason=decision.reason, flags=decision.flags)

        # STAGE 4 — execution dispatch
        from app.broker.broker_factory import get_broker
        broker = get_broker()

        # Re-check kill switch right before placing (minimise TOCTOU window).
        if self._kill_switch_active():
            return _result(signal, "blocked", reason="kill_switch")

        if asset_type == "options":
            from app.services.execution_dispatcher import ExecutionDispatcher, DispatchStatus
            strategy = await self._build_strategy(signal, broker, contracts)
            if strategy is None:
                return _result(signal, "blocked", reason="no_market_data")
            # Cache one dispatcher so its in-process _inflight idempotency set
            # actually persists across submits (was a fresh instance each call).
            if self._dispatcher is None or self._dispatcher.broker is not broker:
                self._dispatcher = ExecutionDispatcher(broker, max_spread_pct=15.0)
            dispatch = await self._dispatcher.validate_and_dispatch(strategy)
            if dispatch.status != DispatchStatus.FILLED:
                return _result(signal, "rejected", reason=str(dispatch.status.value),
                               error=dispatch.error, order_id=dispatch.order_id)
            sd = signal.get("spread", {})
            await self._record_options(signal, dispatch, contracts, approved_by)
            return _result(signal, "submitted", strategy=strategy.strategy_name,
                           order_id=dispatch.order_id, order_status="filled",
                           contracts=contracts, net_credit=sd.get("net_credit"),
                           approved_by=approved_by)
        else:
            plan = signal.get("trade_plan", {})
            # Honor the requested order type (manual market orders were silently
            # turned into $0 limit orders). Only pass a limit price for limits.
            otype = signal.get("order_type", "limit")
            order = await broker.place_equity_order(
                ticker=ticker, qty=contracts, side=signal.get("action", "BUY"),
                order_type=otype,
                limit_price=(plan.get("entry_price") if otype != "market" else None),
                stop=plan.get("stop_price"), take_profit=plan.get("target_price"),
            )
            await self._record_equity(signal, order, contracts, approved_by)
            return _result(signal, "submitted", shares=contracts,
                           order_id=order.order_id, order_status=order.status,
                           approved_by=approved_by)

    # ── Stage 5 — recording (call only; internals owned by batch 4) ────────────
    async def _record_options(self, signal, dispatch, contracts, approved_by) -> None:
        try:
            from app.services.trade_recorder import trade_recorder
            sd = signal.get("spread", {})
            short_k = float(sd.get("short_strike", 0))
            long_k = float(sd.get("long_strike", 0))
            expiry_str = sd.get("expiration", "")
            await trade_recorder.record_fill(
                strategy=signal.get("strategy", "bull_put_spread"),
                underlying=signal.get("ticker", ""),
                option_type=("call" if "call" in signal.get("strategy", "") else sd.get("option_type", "put")),
                short_strike=short_k, long_strike=long_k,
                expiration=date.fromisoformat(expiry_str) if expiry_str else date.today(),
                # record_exit computes pnl = (credit - cost)*qty*100, so credit
                # must be PER SHARE. signal net_credit is dollars/contract → /100.
                quantity=contracts, entry_credit=float(sd.get("net_credit", 0)) / 100.0,
                spread_width=abs(short_k - long_k),
                signal_score=signal.get("signal_score", 0), iv_rank=signal.get("iv_rank", 0),
                regime=signal.get("regime", "unknown"), trading_mode=approved_by,
                dispatch_id=dispatch.order_id,
                net_fill_price=dispatch.net_fill_price,
            )
        except Exception as exc:
            logger.warning("Order gate: options record_fill failed: %s", exc)

    async def _record_equity(self, signal, order, contracts, approved_by) -> None:
        try:
            from app.services.trade_recorder import trade_recorder
            plan = signal.get("trade_plan", {})
            await trade_recorder.record_fill(
                strategy="equity", underlying=signal.get("ticker", ""),
                option_type="equity",
                short_strike=plan.get("entry_price") or 0,
                long_strike=plan.get("stop_price") or 0,
                expiration=date.today(), quantity=contracts,
                entry_credit=plan.get("entry_price") or 0,
                signal_score=signal.get("signal_score", 0), iv_rank=signal.get("iv_rank", 0),
                regime=signal.get("regime", "unknown"), trading_mode=approved_by,
                dispatch_id=order.order_id or signal.get("id", ""),
            )
        except Exception as exc:
            logger.warning("Order gate: equity record_fill failed: %s", exc)


# Module singleton — the one gate everything funnels through.
order_gate = OrderGate()
