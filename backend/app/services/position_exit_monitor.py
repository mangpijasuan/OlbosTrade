"""
Live position exit monitor — enforces trading-mode profit/DTE/stop rules.

Runs on a background interval and closes open options positions when
strategy_engine.check_exit() says they should exit.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.strategy_engine import (
    BearCallSpread,
    BullCallDebitSpread,
    BullPutSpread,
    ExitDecision,
    IronCondor,
)

from app.services.options_pricer import BlackScholesPricer
from app.services.trading_mode import TradingModeType, trading_mode_manager
from app.utils.logger import get_logger

logger = get_logger(__name__)

ET = ZoneInfo("America/New_York")

STRATEGIES = {
    "bull_put_spread":        BullPutSpread(),
    "bear_call_spread":       BearCallSpread(),
    "iron_condor":            IronCondor(),
    "bull_call_debit_spread": BullCallDebitSpread(),
}

SCALPER_INTRADAY_EXIT_HOUR = 15
SCALPER_INTRADAY_EXIT_MINUTE = 30


class PositionExitMonitor:
    """Evaluate open trades and submit close orders when exit rules trigger."""

    def __init__(self) -> None:
        self.pricer = BlackScholesPricer()

    async def run(self) -> list[dict]:
        """Check all open options trades and close those meeting exit criteria."""
        results: list[dict] = []

        try:
            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                rows = (await session.execute(
                    select(Trade).where(Trade.status == "open")
                )).scalars().all()
        except Exception as exc:
            logger.debug("Exit monitor DB unavailable: %s", exc)
            return results

        if not rows:
            return results

        spot, sigma = await self._get_spy_market()
        now_et = datetime.now(ET)

        for trade in rows:
            if str(trade.strategy) == "equity":
                continue

            strategy_key = str(trade.strategy)
            strategy_obj = STRATEGIES.get(strategy_key)
            if strategy_obj is None:
                continue

            dte_remaining = max((trade.expiration - date.today()).days, 0)
            entry_credit = float(trade.credit_received or 0)
            opt_type = "call" if "call" in str(trade.spread_type) else "put"
            short_strike = float(trade.short_strike)
            long_strike = float(trade.long_strike)

            current_value = self._estimate_spread_value(
                spot=spot,
                sigma=sigma,
                dte_remaining=dte_remaining,
                short_strike=short_strike,
                long_strike=long_strike,
                opt_type=opt_type,
            )

            short_breached = (
                spot < short_strike if opt_type == "put" else spot > short_strike
            )

            if strategy_key == "iron_condor":
                exit_decision = strategy_obj.check_exit(
                    entry_credit,
                    current_value,
                    dte_remaining,
                    short_strike_breached=spot < short_strike,
                    short_call_strike_breached=spot > float(trade.short_strike_2 or 0),
                )
            else:
                exit_decision = strategy_obj.check_exit(
                    entry_credit,
                    current_value,
                    dte_remaining,
                    short_strike_breached=short_breached,
                )

            if not exit_decision.should_exit and self._scalper_intraday_exit(
                dte_remaining, now_et,
            ):
                exit_decision = ExitDecision(
                    should_exit=True,
                    reason="scalper_intraday_time_stop",
                    urgency="immediate",
                )

            if not exit_decision.should_exit:
                continue

            closed = await self._close_trade(trade, exit_decision.reason or "mode_exit")
            results.append({
                "trade_id": str(trade.id),
                "strategy": strategy_key,
                "reason": exit_decision.reason,
                "closed": closed,
            })

        return results

    def _scalper_intraday_exit(self, dte_remaining: int, now_et: datetime) -> bool:
        """Force exit on 0DTE scalper positions before market close."""
        cfg = trading_mode_manager.config
        if cfg.mode != TradingModeType.SCALPER:
            return False
        if dte_remaining > 0:
            return False
        exit_time = now_et.replace(
            hour=SCALPER_INTRADAY_EXIT_HOUR,
            minute=SCALPER_INTRADAY_EXIT_MINUTE,
            second=0,
            microsecond=0,
        )
        return now_et >= exit_time

    async def _get_spy_market(self) -> tuple[float, float]:
        try:
            import yfinance as yf
            import numpy as np

            hist = yf.Ticker("SPY").history(period="30d")
            if len(hist) < 5:
                return 500.0, 0.20
            spot = float(hist["Close"].iloc[-1])
            rets = np.log(hist["Close"] / hist["Close"].shift()).dropna()
            sigma = float(rets.std() * np.sqrt(252)) if len(rets) > 3 else 0.20
            return spot, max(sigma, 0.10)
        except Exception:
            return 500.0, 0.20

    def _estimate_spread_value(
        self,
        spot: float,
        sigma: float,
        dte_remaining: int,
        short_strike: float,
        long_strike: float,
        opt_type: str,
    ) -> float:
        """Estimate current cost to close the spread (per contract $)."""
        T = max(dte_remaining / 365.0, 1 / (252 * 6.5))
        r = 0.05
        try:
            if opt_type == "put":
                short_px = self.pricer.put_price(spot, short_strike, T, r, sigma)
                long_px = self.pricer.put_price(spot, long_strike, T, r, sigma)
            else:
                short_px = self.pricer.call_price(spot, short_strike, T, r, sigma)
                long_px = self.pricer.call_price(spot, long_strike, T, r, sigma)
            return round(max(short_px - long_px, 0.0) * 100, 2)
        except Exception:
            return 0.0

    async def _close_trade(self, trade, exit_reason: str) -> bool:
        """Submit a closing spread order and record the exit."""
        try:
            from app.broker.broker_factory import get_broker
            from app.broker.broker_interface import SpreadLeg, SpreadOrder
            from app.services.trade_recorder import trade_recorder
            from decimal import Decimal

            opt_type = "call" if "call" in str(trade.spread_type) else "put"
            qty = int(trade.quantity or 1)

            order = SpreadOrder(
                strategy=str(trade.strategy),
                underlying=str(trade.underlying),
                legs=[
                    SpreadLeg(
                        symbol=str(trade.underlying),
                        expiration=trade.expiration,
                        strike=trade.short_strike,
                        option_type=opt_type,
                        action="BUY",
                        quantity=qty,
                    ),
                    SpreadLeg(
                        symbol=str(trade.underlying),
                        expiration=trade.expiration,
                        strike=trade.long_strike,
                        option_type=opt_type,
                        action="SELL",
                        quantity=qty,
                    ),
                ],
                limit_price=Decimal("0.05"),
                time_in_force="DAY",
            )

            broker = get_broker()
            result = await broker.place_order(order)

            entry_credit = float(trade.credit_received or 0)
            cost_to_close = float(getattr(result, "fill_price", 0) or entry_credit * 0.5)

            await trade_recorder.record_exit(
                trade_id=str(trade.id),
                cost_to_close=cost_to_close,
                exit_reason=exit_reason,
            )
            logger.info(
                "Exit monitor closed %s (%s) — %s",
                trade.id, trade.strategy, exit_reason,
            )
            return True
        except Exception as exc:
            logger.warning("Exit monitor failed to close %s: %s", trade.id, exc)
            return False


position_exit_monitor = PositionExitMonitor()
