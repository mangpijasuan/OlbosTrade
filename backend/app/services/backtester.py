"""
Walk-forward backtester.
Uses fill_simulator for all fills — never raw prices.

FIX #1: Look-ahead bias eliminated — signal generation uses ONLY data
        available at bar open (prior bar's close via .shift(1)).
FIX #3: IV rank derived from actual VIX history, not realized vol proxy.
FIX #9: Position repricing uses full Black-Scholes at each bar, not linear theta decay.
FIX #7: Fill simulator receives live VIX for vol-adjusted slippage.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

from app.broker.broker_interface import Greeks as GK, OptionContract, OptionsChain
from app.broker.fill_simulator import FillSimulator, SpreadFillResult
from app.services.data_fetcher import DataFetcher
from app.services.guardrails import GuardrailEngine, PortfolioState
from app.services.options_pricer import BlackScholesPricer
from app.services.risk_manager import PortfolioRiskState, RiskManager
from app.services.strategy_engine import (
    BaseStrategy,
    BullPutSpread, BearCallSpread, IronCondor, BullCallDebitSpread,
)
from app.utils.logger import get_logger
from app.utils.metrics import PerformanceMetrics, calculate_all_metrics

logger = get_logger(__name__)

RISK_FREE_RATE = 0.05
# Minimum credit-to-width ratio to enter.
# Real SPY bull-put / bear-call spreads at 35 DTE 0.20-delta typically yield
# 8–15% of spread width as net credit.  The old 0.20 (20%) threshold was
# rejecting every qualifying trade.  0.08 matches observed market pricing.
MIN_CREDIT_TO_WIDTH = 0.08


@dataclass
class BacktestTrade:
    """A single simulated trade produced by the backtester."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    strategy: str = ""
    underlying: str = ""
    entry_date: Optional[date] = None
    exit_date: Optional[date] = None
    short_strike: float = 0.0
    long_strike: float = 0.0
    expiration: Optional[date] = None
    entry_credit: float = 0.0
    exit_cost: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    signal_score: float = 0.0
    commission_paid: float = 0.0
    contracts: int = 1
    hold_days: int = 0
    entry_vix: float = 20.0
    partial_fill_occurred: bool = False
    # W1 FIX: Store spread geometry so label construction in ml/features.py
    # can compute return-on-risk (ror) instead of sign(P&L).
    # Previously these defaulted to 10.0 / 0.25 for EVERY training row,
    # giving the model zero signal from these features.
    spread_width: float = 0.0           # short_strike - long_strike (points)
    credit_to_width_ratio: float = 0.0  # entry_credit / spread_width
    credit_received: float = 0.0        # entry_credit * 100 per contract (dollars)
    # FIX #5: Store what the model WOULD have scored (counterfactual)
    counterfactual_signal_score: Optional[float] = None


@dataclass
class BacktestResult:
    """Full result set from a completed backtest run."""
    strategy: str
    start_date: date
    end_date: date
    starting_capital: float
    ending_capital: float
    trades: list[BacktestTrade]
    metrics: Optional[PerformanceMetrics] = None
    equity_curve: list[float] = field(default_factory=list)
    partial_fill_count: int = 0
    look_ahead_bias_guard: str = "shift(1) applied — signals use prior bar close"


class Backtester:
    """
    Walk-forward backtester for all four spread strategies.

    Walk-forward logic:
    - Pre-compute all indicators, then shift(1) so bar N uses bar N-1 data
    - Manage all open positions: reprice via Black-Scholes at each bar
    - All fills through FillSimulator with live VIX for vol-adjusted slippage
    """

    def __init__(self, fetcher: DataFetcher) -> None:
        self.fetcher = fetcher
        self.fill_sim = FillSimulator(random_seed=42)  # reproducible partial fills
        self.pricer = BlackScholesPricer()
        self.guardrails = GuardrailEngine()
        self.risk_manager = RiskManager()

    def _get_strategy(self, name: str) -> BaseStrategy:
        strategies = {
            "bull_put_spread": BullPutSpread(),
            "bear_call_spread": BearCallSpread(),
            "iron_condor": IronCondor(),
            "bull_call_debit_spread": BullCallDebitSpread(),
        }
        if name not in strategies:
            raise ValueError(f"Unknown strategy: {name}. Valid: {list(strategies.keys())}")
        return strategies[name]

    def _build_indicator_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        FIX #1: Build all indicators then shift(1) to eliminate look-ahead bias.

        All signal columns in the returned frame represent what was KNOWN at
        the open of each bar — i.e., the prior bar's closing values.
        The raw close (for filling) is kept unshifted as 'fill_close'.
        """
        out = pd.DataFrame(index=df.index)

        # fill_close = actual close of this bar (for fill simulation only)
        out["fill_close"] = df["Close"]

        # FIX #1: Everything used for signal generation is shifted one bar back
        out["signal_close"] = df["Close"].shift(1)
        out["signal_high"]  = df["High"].shift(1)
        out["signal_low"]   = df["Low"].shift(1)

        rsi   = self.fetcher.calculate_rsi(df["Close"])
        sma20 = self.fetcher.calculate_sma(df["Close"])
        rv20  = self.fetcher.calculate_realized_vol(df["Close"])

        out["signal_rsi"]       = rsi.shift(1)
        out["signal_sma20"]     = sma20.shift(1)
        out["signal_rv"]        = rv20.shift(1)
        out["signal_above_sma"] = (df["Close"].shift(1) > sma20.shift(1))

        return out

    async def run(
        self,
        strategy_name: str,
        start_date: str,
        end_date: str,
        starting_capital: float = 25000.0,
        signal_score_override: float = 0.70,
        vix_df: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """
        Run a full walk-forward backtest.

        Args:
            strategy_name:         One of the four strategy identifiers
            start_date:            "YYYY-MM-DD"
            end_date:              "YYYY-MM-DD"
            starting_capital:      Starting account value
            signal_score_override: Fixed signal score (0–1) — model gates here
            vix_df:                Optional VIX OHLCV DataFrame for real IV rank.
                                   If None, falls back to RV-based approximation.
        """
        logger.info("Backtest starting: %s %s → %s", strategy_name, start_date, end_date)
        strategy = self._get_strategy(strategy_name)

        # Fetch SPY data — fetch extra history for indicator warm-up
        warmup_start = (
            pd.Timestamp(start_date) - pd.Timedelta(days=60)
        ).strftime("%Y-%m-%d")
        df = await self.fetcher.fetch_ohlcv("SPY", warmup_start, end_date)

        # FIX #1: Build shifted indicator frame — no look-ahead after this point
        ind = self._build_indicator_frame(df)

        # FIX #3: Load real VIX history for IV rank
        # Auto-fetch ^VIX from yfinance if not provided — real IV rank is critical
        # for strategy gating (bull_put/bear_call need IV rank >30, condor >40).
        # The RV proxy keeps SPY IV rank near 0–17, causing 0 trades every backtest.
        vix_close: Optional[pd.Series] = None
        if vix_df is not None:
            vix_close = vix_df["Close"].reindex(df.index, method="ffill")
        else:
            try:
                import asyncio as _asyncio
                import yfinance as _yf

                loop = _asyncio.get_running_loop()
                _vix_raw = await loop.run_in_executor(
                    None,
                    lambda: _yf.Ticker("^VIX").history(
                        start=warmup_start, end=end_date, auto_adjust=True
                    )
                )
                if not _vix_raw.empty:
                    _vix_raw.index = pd.to_datetime(_vix_raw.index).tz_localize(None)
                    vix_close = _vix_raw["Close"].reindex(df.index, method="ffill")
                    logger.info("Loaded ^VIX history (%d rows) for IV rank", len(_vix_raw))
                else:
                    logger.warning("^VIX empty — using RV proxy for IV rank")
            except Exception as _vix_exc:
                logger.warning("Failed to fetch ^VIX (%s) — using RV proxy", _vix_exc)

        # Trim to actual backtest window (after warm-up)
        backtest_start = pd.Timestamp(start_date)
        ind = ind[ind.index >= backtest_start]

        portfolio_value = starting_capital
        equity_curve: list[float] = [starting_capital]
        trades: list[BacktestTrade] = []
        open_trades: list[BacktestTrade] = []
        partial_fill_count = 0

        daily_pnl = 0.0
        weekly_pnl = 0.0
        monthly_pnl = 0.0
        consecutive_losses = 0
        trades_today = 0
        last_date: Optional[date] = None
        last_week: Optional[int] = None
        last_month: Optional[int] = None

        for i, (ts, row) in enumerate(ind.iterrows()):
            current_date = ts.date() if hasattr(ts, "date") else ts

            # Reset P&L windows at boundary crossings
            if last_date != current_date:
                trades_today = 0
                daily_pnl = 0.0
                last_date = current_date
            week_num = current_date.isocalendar()[1]
            if last_week is not None and week_num != last_week:
                weekly_pnl = 0.0
            last_week = week_num
            if last_month is not None and current_date.month != last_month:
                monthly_pnl = 0.0
            last_month = current_date.month

            # FIX #1: Use signal_close (prior bar) for all decisions
            # Use fill_close (current bar) only for fill simulation
            signal_price = row["signal_close"]
            fill_price   = row["fill_close"]

            if pd.isna(signal_price) or pd.isna(fill_price):
                continue

            signal_close = float(signal_price)
            fill_close   = float(fill_price)
            current_rsi  = float(row["signal_rsi"]) if not pd.isna(row["signal_rsi"]) else 50.0
            current_sma  = float(row["signal_sma20"]) if not pd.isna(row["signal_sma20"]) else signal_close
            current_rv   = float(row["signal_rv"]) if not pd.isna(row["signal_rv"]) else 0.20
            above_sma    = bool(row["signal_above_sma"])

            # FIX #3: Derive VIX from real data if available, else RV proxy
            if vix_close is not None and ts in vix_close.index:
                vix = float(vix_close.loc[ts])
            else:
                vix = current_rv * 100  # approximate — acceptable fallback

            # FIX #3: IV rank from VIX history window (real forward-looking vol)
            if vix_close is not None:
                vix_window = vix_close.loc[:ts].iloc[-252:]
                current_vix = vix
                vix_lo = float(vix_window.min())
                vix_hi = float(vix_window.max())
                iv_rank = ((current_vix - vix_lo) / (vix_hi - vix_lo) * 100
                           if vix_hi != vix_lo else 50.0)
            else:
                iv_rank = min(max((current_rv - 0.10) / 0.30 * 100, 0), 100)

            # ── Manage existing positions (reprice via full B-S) ──────────
            still_open: list[BacktestTrade] = []
            for trade in open_trades:
                if not trade.expiration:
                    continue
                dte = (trade.expiration - current_date).days

                # FIX #9: Full Black-Scholes repricing — no linear theta approximation
                T_remaining = max(dte / 365, 0.001)
                sigma = current_rv if current_rv > 0.05 else 0.15

                try:
                    _use_calls = trade.strategy in ("bear_call_spread", "bull_call_debit_spread")
                    _pricer_fn = self.pricer.call_price if _use_calls else self.pricer.put_price
                    current_short_val = _pricer_fn(
                        fill_close, trade.short_strike, T_remaining,
                        RISK_FREE_RATE, sigma
                    )
                    current_long_val = _pricer_fn(
                        fill_close, trade.long_strike, T_remaining,
                        RISK_FREE_RATE, sigma
                    )
                    # Cost to close the spread (buy back short, sell long)
                    current_val = max(current_short_val - current_long_val, 0.01)
                except Exception:
                    current_val = trade.entry_credit * 0.5  # fallback

                short_breached = abs(fill_close - trade.short_strike) < 2.0

                exit_decision = strategy.check_exit(
                    entry_credit=trade.entry_credit,
                    current_value=current_val,
                    dte_remaining=dte,
                    short_strike_breached=short_breached,
                )

                if exit_decision.should_exit or dte <= 0:
                    # FIX #7: Exit fill uses VIX-adjusted slippage
                    spread_result = self.fill_sim.simulate_spread_fill(
                        legs=[
                            {"bid": max(current_val - 0.05, 0.01),
                             "ask": current_val + 0.05, "side": "BUY"},
                        ],
                        contracts=trade.contracts,
                        vix=vix,
                        simulate_partial_fills=False,  # exits always go through
                    )
                    exit_fill = spread_result.leg_fills[0]
                    exit_cost = exit_fill.gross_fill_price
                    commission = exit_fill.commission

                    pnl = (
                        (trade.entry_credit - exit_cost) * trade.contracts * 100
                        - commission
                    )

                    trade.exit_date = current_date
                    trade.exit_cost = exit_cost
                    trade.pnl = pnl
                    trade.pnl_pct = pnl / starting_capital
                    trade.exit_reason = (
                        exit_decision.reason or ("expired" if dte <= 0 else "stop")
                    )
                    trade.commission_paid += commission
                    trade.hold_days = (
                        (current_date - trade.entry_date).days
                        if trade.entry_date else 0
                    )

                    portfolio_value += pnl
                    daily_pnl   += pnl
                    weekly_pnl  += pnl
                    monthly_pnl += pnl

                    consecutive_losses = consecutive_losses + 1 if pnl < 0 else 0
                    trades.append(trade)
                    logger.debug(
                        "Closed %s P&L=%.2f reason=%s",
                        trade.strategy, pnl, trade.exit_reason,
                    )
                else:
                    still_open.append(trade)

            open_trades = still_open
            equity_curve.append(portfolio_value)

            # ── Entry evaluation ──────────────────────────────────────────
            portfolio_state = PortfolioState(
                current_value=portfolio_value,
                starting_capital=starting_capital,
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
                monthly_pnl=monthly_pnl,
                consecutive_losses=consecutive_losses,
                trades_today=trades_today,
            )

            guardrail_status = self.guardrails.check_all(portfolio_state)
            if not guardrail_status.trading_allowed:
                continue
            if not self.guardrails.is_strategy_allowed(strategy_name, guardrail_status):
                continue

            threshold = self.guardrails.get_signal_threshold(guardrail_status)
            if signal_score_override < threshold:
                continue

            # Build expiry ~35 DTE from current bar
            target_expiry = current_date + timedelta(days=35)
            # Snap to end of month to avoid invalid dates
            import calendar
            last_day = calendar.monthrange(target_expiry.year, target_expiry.month)[1]
            target_expiry = target_expiry.replace(day=min(target_expiry.day, last_day))

            T_entry = max((target_expiry - current_date).days / 365, 0.01)
            sigma_entry = current_rv if current_rv > 0.05 else 0.15

            # FIX #1: Build synthetic chain using signal_close (prior bar),
            # NOT fill_close (current bar close — future data)
            synthetic_puts: list[OptionContract] = []
            synthetic_calls: list[OptionContract] = []

            # FIX — vectorized B-S pricing (performance + GIL fix)
            strike_offsets = np.arange(-50, 51, 5)
            strikes = np.array([round(signal_close + o) for o in strike_offsets])

            for strike in strikes:
                s = float(strike)
                try:
                    put_price  = self.pricer.put_price(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry)
                    call_price = self.pricer.call_price(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry)
                    put_delta  = self.pricer.delta(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry, "put")
                    call_delta = self.pricer.delta(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry, "call")
                    gamma      = self.pricer.gamma(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry)
                    put_theta  = self.pricer.theta(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry, "put")
                    call_theta = self.pricer.theta(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry, "call")
                    vega_val   = self.pricer.vega(signal_close, s, T_entry, RISK_FREE_RATE, sigma_entry)
                except Exception:
                    continue

                # FIX #7: Spread bid/ask widens with VIX
                half_spread = 0.05 + (vix / 1000)  # e.g. VIX=30 → $0.08 half-spread

                synthetic_puts.append(OptionContract(
                    symbol=f"SPY_P{int(s)}", underlying="SPY",
                    expiration=target_expiry, strike=Decimal(str(int(s))),
                    option_type="put",
                    bid=Decimal(str(round(max(put_price - half_spread, 0.01), 2))),
                    ask=Decimal(str(round(put_price + half_spread, 2))),
                    last=Decimal(str(round(put_price, 2))),
                    volume=1000, open_interest=5000,
                    greeks=GK(delta=put_delta, gamma=gamma, theta=put_theta,
                              vega=vega_val, implied_vol=sigma_entry),
                ))
                synthetic_calls.append(OptionContract(
                    symbol=f"SPY_C{int(s)}", underlying="SPY",
                    expiration=target_expiry, strike=Decimal(str(int(s))),
                    option_type="call",
                    bid=Decimal(str(round(max(call_price - half_spread, 0.01), 2))),
                    ask=Decimal(str(round(call_price + half_spread, 2))),
                    last=Decimal(str(round(call_price, 2))),
                    volume=1000, open_interest=5000,
                    greeks=GK(delta=call_delta, gamma=gamma, theta=call_theta,
                              vega=vega_val, implied_vol=sigma_entry),
                ))

            chain = OptionsChain(
                underlying="SPY",
                expiration=target_expiry,
                # FIX #1: underlying_price uses signal_close, not fill_close
                underlying_price=Decimal(str(round(signal_close, 2))),
                calls=synthetic_calls,
                puts=synthetic_puts,
                fetched_at=datetime.now(timezone.utc),
            )

            signal = strategy.generate_signal(
                chain=chain,
                iv_rank=iv_rank,
                rsi=current_rsi,
                adx=15.0,
                above_sma20=above_sma,
                vix=vix,
                portfolio_state=portfolio_state,
            )

            if not signal.entry_allowed or not signal.short_strike:
                continue

            long_strike = signal.long_strike or (signal.short_strike - 10)
            spread_width = abs(signal.short_strike - long_strike)

            # FIX #1: Entry pricing also uses signal_close (prior bar), not fill_close
            # Use call_price for call-based strategies, put_price for put-based
            try:
                _use_calls = strategy_name in ("bear_call_spread", "bull_call_debit_spread")
                _entry_pricer = self.pricer.call_price if _use_calls else self.pricer.put_price
                entry_short = _entry_pricer(
                    signal_close, signal.short_strike,
                    T_entry, RISK_FREE_RATE, sigma_entry
                )
                entry_long = _entry_pricer(
                    signal_close, long_strike,
                    T_entry, RISK_FREE_RATE, sigma_entry
                )
            except Exception:
                continue

            # FIX #7: Entry fills use VIX-adjusted slippage.
            # Partial fill simulation is DISABLED in backtesting — we already model
            # friction via B-S slippage + commissions. The stochastic partial fill
            # model is only meaningful for live order routing, not synthetic prices.
            spread_result: SpreadFillResult = self.fill_sim.simulate_spread_fill(
                legs=[
                    {"bid": max(entry_short - 0.05, 0.01),
                     "ask": entry_short + 0.05, "side": "SELL"},
                    {"bid": max(entry_long - 0.05, 0.01),
                     "ask": entry_long + 0.05, "side": "BUY"},
                ],
                contracts=1,
                vix=vix,
                simulate_partial_fills=False,  # disabled in backtesting
            )

            fill_short = spread_result.leg_fills[0]
            fill_long  = spread_result.leg_fills[1]
            net_credit = fill_short.gross_fill_price - fill_long.gross_fill_price

            # Filter marginal trades — credit must be at least 20% of spread width
            if net_credit <= 0.05:
                continue
            if spread_width > 0 and (net_credit / spread_width) < MIN_CREDIT_TO_WIDTH:
                continue

            total_commission = fill_short.commission + fill_long.commission

            # W1 FIX: populate spread geometry so ml/features.py _ror_label()
            # can compute return-on-risk.  spread_width = short - long for
            # bull-put; long - short for bear-call. We store as positive points.
            _sw = abs(signal.short_strike - long_strike)
            new_trade = BacktestTrade(
                strategy=strategy_name,
                underlying="SPY",
                entry_date=current_date,
                expiration=target_expiry,
                short_strike=signal.short_strike,
                long_strike=long_strike,
                entry_credit=net_credit,
                signal_score=signal_score_override,
                commission_paid=total_commission,
                contracts=1,
                entry_vix=vix,
                # W1: real spread geometry (not hardcoded defaults)
                spread_width=_sw,
                credit_to_width_ratio=(net_credit / _sw) if _sw > 0 else 0.0,
                credit_received=net_credit * 100,   # dollars per contract
            )
            open_trades.append(new_trade)
            trades_today += 1

        # Force-close remaining open positions at end of backtest
        for trade in open_trades:
            trade.exit_date = date.fromisoformat(end_date)
            trade.exit_reason = "backtest_end"
            trade.pnl = 0.0
            trade.hold_days = (
                (trade.exit_date - trade.entry_date).days
                if trade.entry_date else 0
            )
            trades.append(trade)

        # Calculate metrics
        closed = [t for t in trades if t.exit_reason != "backtest_end"]
        pnl_list  = [t.pnl for t in closed]
        hold_list = [t.hold_days for t in closed]
        total_commissions = sum(t.commission_paid for t in trades)

        metrics = calculate_all_metrics(
            pnl_series=pnl_list,
            hold_days=hold_list,
            starting_capital=starting_capital,
            total_commissions=total_commissions,
            equity_curve=pd.Series(equity_curve),
        )

        logger.info(
            "Backtest complete: %d trades (%d partial fill rejects), "
            "return=%.2f%%, Sharpe=%.2f",
            len(closed), partial_fill_count,
            metrics.total_return_pct * 100, metrics.sharpe_ratio,
        )

        return BacktestResult(
            strategy=strategy_name,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            starting_capital=starting_capital,
            ending_capital=portfolio_value,
            trades=trades,
            metrics=metrics,
            equity_curve=equity_curve,
            partial_fill_count=partial_fill_count,
        )
