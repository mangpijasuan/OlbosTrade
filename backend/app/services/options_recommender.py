"""Top-ranked option buying setup recommendations."""
from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import pandas as pd

from app.broker.broker_interface import OptionContract, OptionsChain
from app.core.config import settings
from app.services.equity_signal_engine import compute_indicators, score_equity_signal
from app.services.trading_mode import trading_mode_manager
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_RECOMMENDATION_SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "META"]


def _next_friday_on_or_after(target: date) -> date:
    """Return the first Friday on or after target."""
    days = (4 - target.weekday()) % 7
    return target + timedelta(days=days)


def _strike_increment(price: float) -> float:
    if price >= 200:
        return 5.0
    if price >= 50:
        return 2.5
    return 1.0


def _round_strike(value: float, increment: float, direction: str) -> float:
    if direction == "up":
        return round(math.ceil(value / increment) * increment, 2)
    if direction == "down":
        return round(math.floor(value / increment) * increment, 2)
    return round(round(value / increment) * increment, 2)


def _mid_price(contract: OptionContract | None) -> float | None:
    if contract is None:
        return None
    bid = float(contract.bid or 0)
    ask = float(contract.ask or 0)
    last = float(contract.last or 0)
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2, 2)
    if last > 0:
        return round(last, 2)
    return None


def _find_contract(
    contracts: Iterable[OptionContract],
    strike: float,
) -> OptionContract | None:
    return min(contracts, key=lambda c: abs(float(c.strike) - strike), default=None)


class OptionsSetupRecommender:
    """Builds ranked option buying setups from watchlist signals."""

    def __init__(self, broker=None) -> None:
        self._broker = broker

    async def recommend(
        self,
        symbols: list[str] | None = None,
        limit: int = 5,
    ) -> dict:
        clean_symbols = [
            s.strip().upper()
            for s in (symbols or DEFAULT_RECOMMENDATION_SYMBOLS)
            if s.strip()
        ]
        if not clean_symbols:
            clean_symbols = DEFAULT_RECOMMENDATION_SYMBOLS

        tasks = [self._build_for_symbol(symbol) for symbol in clean_symbols[:12]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        setups = [r for r in results if isinstance(r, dict)]
        setups.sort(key=lambda r: r.get("rank_score", 0), reverse=True)
        for idx, setup in enumerate(setups, start=1):
            setup["rank"] = idx

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": trading_mode_manager.current.active_mode.value,
            "dte_window": {
                "min": trading_mode_manager.config.dte_min,
                "target": trading_mode_manager.config.dte_target,
                "max": trading_mode_manager.config.dte_max,
            },
            "count": min(limit, len(setups)),
            "recommendations": setups[:limit],
        }

    async def _build_for_symbol(self, symbol: str) -> dict | None:
        bars = await self._fetch_bars(symbol)
        if len(bars) < 60:
            return None

        indicators = compute_indicators(bars)
        if not indicators:
            return None

        action, confidence, reasons = score_equity_signal(indicators)
        direction = self._direction_from_signal(action, indicators)
        if direction is None:
            return None

        price = float(indicators["close"])
        atr = max(float(indicators.get("atr") or price * 0.015), price * 0.005)
        mode = trading_mode_manager.config
        expiry = _next_friday_on_or_after(date.today() + timedelta(days=mode.dte_target))
        dte = max((expiry - date.today()).days, 1)
        increment = _strike_increment(price)
        width = max(increment, _round_strike(max(price * 0.025, atr * 1.5), increment, "nearest"))

        if direction == "bullish":
            option_type = "call"
            strategy = "bull_call_debit_spread"
            buy_strike = _round_strike(price * 1.00, increment, "up")
            sell_strike = round(buy_strike + width, 2)
            thesis = "Bullish call debit spread"
        else:
            option_type = "put"
            strategy = "bear_put_debit_spread"
            buy_strike = _round_strike(price * 1.00, increment, "down")
            sell_strike = round(max(increment, buy_strike - width), 2)
            thesis = "Bearish put debit spread"

        chain = await self._try_chain(symbol, expiry.isoformat())
        debit, chain_source, leg_prices = self._estimate_debit(
            chain=chain,
            option_type=option_type,
            buy_strike=buy_strike,
            sell_strike=sell_strike,
            width=abs(sell_strike - buy_strike),
        )

        spread_width = abs(sell_strike - buy_strike)
        max_risk = round(debit * 100, 2)
        max_profit = round(max((spread_width - debit) * 100, 0), 2)
        risk_budget = settings.starting_capital * mode.risk_per_trade_pct
        suggested_contracts = max(1, min(5, int(risk_budget // max(max_risk, 1))))
        rr = round(max_profit / max(max_risk, 1), 2)
        score = self._rank_score(confidence, indicators, rr, chain_source)

        return {
            "rank": 0,  # filled by UI/order after sorting if needed
            "rank_score": score,
            "symbol": symbol,
            "underlying_price": round(price, 2),
            "direction": direction,
            "strategy": strategy,
            "thesis": thesis,
            "option_type": option_type,
            "expiration": expiry.isoformat(),
            "dte": dte,
            "legs_count": 2,
            "strikes": {
                "buy": buy_strike,
                "sell": sell_strike,
                "width": spread_width,
            },
            "legs": [
                {
                    "action": "BUY",
                    "option_type": option_type,
                    "strike": buy_strike,
                    "estimated_price": leg_prices.get("buy"),
                },
                {
                    "action": "SELL",
                    "option_type": option_type,
                    "strike": sell_strike,
                    "estimated_price": leg_prices.get("sell"),
                },
            ],
            "estimated_debit": round(debit, 2),
            "max_risk": max_risk,
            "max_profit": max_profit,
            "risk_reward": rr,
            "suggested_contracts": suggested_contracts,
            "profit_target": round(debit + (spread_width - debit) * 0.5, 2),
            "stop_debit": round(debit * 0.5, 2),
            "confidence": round(max(confidence, 0.35), 4),
            "chain_source": chain_source,
            "rationale": self._rationale(direction, indicators, reasons, chain_source),
        }

    async def _fetch_bars(self, symbol: str) -> pd.DataFrame:
        import yfinance as yf

        loop = asyncio.get_running_loop()

        def _fetch() -> pd.DataFrame:
            hist = yf.Ticker(symbol).history(period="9mo", auto_adjust=True)
            if hist.empty:
                return pd.DataFrame()
            return hist.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )[["open", "high", "low", "close", "volume"]].dropna()

        return await loop.run_in_executor(None, _fetch)

    async def _try_chain(self, symbol: str, expiry: str) -> OptionsChain | None:
        if self._broker is None:
            return None
        try:
            return await self._broker.get_options_chain(symbol, expiry)
        except Exception as exc:
            logger.debug("Options chain unavailable for %s %s: %s", symbol, expiry, exc)
            return None

    def _estimate_debit(
        self,
        chain: OptionsChain | None,
        option_type: str,
        buy_strike: float,
        sell_strike: float,
        width: float,
    ) -> tuple[float, str, dict[str, float | None]]:
        if chain is not None:
            contracts = chain.calls if option_type == "call" else chain.puts
            buy = _find_contract(contracts, buy_strike)
            sell = _find_contract(contracts, sell_strike)
            buy_mid = _mid_price(buy)
            sell_mid = _mid_price(sell)
            if buy_mid is not None and sell_mid is not None and buy_mid > sell_mid:
                return max(round(buy_mid - sell_mid, 2), 0.05), "live_chain", {
                    "buy": buy_mid,
                    "sell": sell_mid,
                }

        # Conservative fallback: assume debit is around 40% of spread width.
        debit = max(round(width * 0.40, 2), 0.05)
        return float(debit), "estimated", {"buy": None, "sell": None}

    def _direction_from_signal(self, action: str, indicators: dict) -> str | None:
        if action == "BUY":
            return "bullish"
        if action == "SELL":
            return "bearish"

        bull = 0
        bear = 0
        if indicators.get("ema_aligned_bull"):
            bull += 2
        if indicators.get("ema_aligned_bear"):
            bear += 2
        if indicators.get("above_ema200"):
            bull += 1
        else:
            bear += 1
        if indicators.get("macd", 0) > indicators.get("macd_signal", 0):
            bull += 1
        else:
            bear += 1
        if bull == bear:
            return None
        return "bullish" if bull > bear else "bearish"

    def _rank_score(self, confidence: float, indicators: dict, rr: float, chain_source: str) -> float:
        score = max(confidence, 0.35) * 100
        score += min(rr, 3.0) * 4
        if chain_source == "live_chain":
            score += 5
        if indicators.get("volume_ratio", 1) > 1.2:
            score += 3
        if indicators.get("ema_aligned_bull") or indicators.get("ema_aligned_bear"):
            score += 4
        return round(score, 2)

    def _rationale(
        self,
        direction: str,
        indicators: dict,
        reasons: dict,
        chain_source: str,
    ) -> list[str]:
        out = [
            f"{direction.title()} bias from EMA/MACD/RSI signal stack",
            f"RSI {float(indicators.get('rsi', 50)):.1f}, volume ratio {float(indicators.get('volume_ratio', 1)):.2f}x",
            "Uses live option mids" if chain_source == "live_chain" else "Uses estimated option prices until IBKR chain is connected",
        ]
        if reasons:
            top = sorted(reasons.items(), key=lambda kv: abs(float(kv[1])), reverse=True)[:2]
            out.append("Top factors: " + ", ".join(k.replace("_", " ") for k, _ in top))
        return out
