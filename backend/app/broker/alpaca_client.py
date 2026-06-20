"""
Alpaca broker implementation using httpx async REST.
Supports equities only — options calls raise NotImplementedError.
Switch to this broker by setting BROKER=alpaca in .env.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Literal

import httpx

from app.broker.broker_interface import (
    AccountSummary,
    Bar,
    BrokerInterface,
    EquityOrderResult,
    Greeks,
    OptionsChain,
    OrderResult,
    Position,
    Quote,
    SpreadOrder,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds, doubled each retry


class AlpacaClient(BrokerInterface):
    """
    Alpaca REST v2 broker client.
    Paper: https://paper-api.alpaca.markets
    Live:  https://api.alpaca.markets
    """

    supports_options: bool = False
    supports_equities: bool = True

    def __init__(self) -> None:
        self._base_url = settings.alpaca_base_url.rstrip("/")
        self._headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
            "Content-Type": "application/json",
        }
        self._data_url = "https://data.alpaca.markets"

    def _is_paper(self) -> bool:
        return "paper" in self._base_url

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        **kwargs,
    ) -> dict:
        """Execute an httpx request with exponential backoff retry on 429/timeout."""
        hdrs = headers or self._headers
        delay = BASE_RETRY_DELAY
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.request(method, url, headers=hdrs, **kwargs)
                    if resp.status_code == 429:
                        logger.warning(
                            "Alpaca rate limit (attempt %d/%d) — sleeping %.1fs",
                            attempt, MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue
                    resp.raise_for_status()
                    return resp.json()
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Alpaca timeout (attempt %d/%d): %s", attempt, MAX_RETRIES, exc
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= 2

        raise ConnectionError(
            f"Alpaca request failed after {MAX_RETRIES} attempts: {last_exc}"
        )

    # ── Options — not supported ─────────────────────────────────────────────

    async def get_options_chain(self, symbol: str, expiry: str) -> OptionsChain:
        raise NotImplementedError("Use IBKR for options")

    async def get_greeks(
        self, symbol: str, strike: float, expiry: str, option_type: str
    ) -> Greeks:
        raise NotImplementedError("Use IBKR for options")

    async def place_order(self, spread: SpreadOrder) -> OrderResult:
        raise NotImplementedError("Use IBKR for options")

    async def get_positions(self) -> list[Position]:
        """
        Alpaca is equity-only. Delegate to get_equity_positions and convert
        EquityPosition → Position so the generic interface works correctly.
        """
        from datetime import date
        from decimal import Decimal
        equity_positions = await self.get_equity_positions()
        positions = []

        def _dec(v) -> Decimal:
            try:
                return Decimal(str(v))
            except Exception:
                return Decimal("0")

        for p in equity_positions:
            if isinstance(p, dict):
                symbol = p.get("symbol", "")
                positions.append(
                    Position(
                        symbol=symbol,
                        underlying=symbol,
                        strike=Decimal("0"),
                        expiration=date.today(),
                        option_type="call",
                        quantity=int(float(p.get("qty", 0) or 0)),
                        avg_cost=_dec(p.get("avg_entry_price", 0)),
                        current_price=_dec(p.get("current_price")) if p.get("current_price") else None,
                        unrealized_pnl=_dec(p.get("unrealized_pl")) if p.get("unrealized_pl") else None,
                    )
                )
            else:
                positions.append(
                    Position(
                        symbol=p.symbol,
                        underlying=p.symbol,
                        strike=Decimal("0"),
                        expiration=date.today(),
                        option_type="call",
                        quantity=p.quantity,
                        avg_cost=p.avg_cost,
                        current_price=p.current_price,
                        unrealized_pnl=p.unrealized_pnl,
                    )
                )
        return positions

    # ── Core BrokerInterface equity methods ─────────────────────────────────

    async def get_account_summary(self) -> AccountSummary:
        """GET /v2/account."""
        data = await self._request("GET", f"{self._base_url}/v2/account")
        return AccountSummary(
            account_id=data.get("id", "unknown"),
            net_liquidation=Decimal(str(data.get("portfolio_value", "0"))),
            cash_balance=Decimal(str(data.get("cash", "0"))),
            buying_power=Decimal(str(data.get("buying_power", "0"))),
            day_trades_remaining=int(data.get("daytrade_count", 0)),
            trading_mode="paper" if self._is_paper() else "live",
        )

    async def place_equity_order(
        self,
        ticker: str,
        qty: int,
        side: Literal["BUY", "SELL"],
        order_type: Literal["market", "limit", "stop", "stop_limit"] = "market",
        limit_price: float | None = None,
        stop: float | None = None,
        take_profit: float | None = None,
    ) -> EquityOrderResult:
        """POST /v2/orders — bracket orders supported."""
        payload: dict = {
            "symbol": ticker,
            "qty": str(qty),
            "side": side.lower(),
            "type": order_type,
            "time_in_force": "day",
        }
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if stop is not None:
            payload["stop_price"] = str(stop)

        if stop is not None and take_profit is not None:
            payload["order_class"] = "bracket"
            payload["stop_loss"] = {"stop_price": str(stop)}
            payload["take_profit"] = {"limit_price": str(take_profit)}
        elif stop is not None:
            payload["order_class"] = "oto"
            payload["stop_loss"] = {"stop_price": str(stop)}

        data = await self._request(
            "POST", f"{self._base_url}/v2/orders", json=payload
        )
        fill_price = None
        if data.get("filled_avg_price"):
            fill_price = Decimal(str(data["filled_avg_price"]))
        filled_at = None
        if data.get("filled_at"):
            filled_at = datetime.fromisoformat(data["filled_at"].replace("Z", "+00:00"))

        status_map = {
            "new": "submitted",
            "partially_filled": "submitted",
            "filled": "filled",
            "canceled": "cancelled",
            "cancelled": "cancelled",
            "rejected": "rejected",
            "pending_new": "pending",
        }
        raw_status = data.get("status", "pending")
        mapped_status = status_map.get(raw_status, "pending")

        return EquityOrderResult(
            order_id=data.get("id", ""),
            status=mapped_status,
            fill_price=fill_price,
            filled_at=filled_at,
            message=raw_status,
        )

    async def get_bars(
        self, ticker: str, timeframe: str = "1Day", limit: int = 100
    ) -> list[Bar]:
        """GET /v2/stocks/{symbol}/bars from Alpaca data API."""
        url = f"{self._data_url}/v2/stocks/{ticker}/bars"
        params = {
            "timeframe": timeframe,
            "limit": limit,
            "adjustment": "raw",
            "feed": "iex",
        }
        data = await self._request("GET", url, params=params)
        bars_raw = data.get("bars", [])
        result = []
        for b in bars_raw:
            ts_str = b.get("t", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.utcnow()
            result.append(Bar(
                timestamp=ts,
                open=Decimal(str(b.get("o", 0))),
                high=Decimal(str(b.get("h", 0))),
                low=Decimal(str(b.get("l", 0))),
                close=Decimal(str(b.get("c", 0))),
                volume=int(b.get("v", 0)),
            ))
        return result

    async def get_latest_quote(self, ticker: str) -> Quote:
        """GET /v2/stocks/{symbol}/quotes/latest from Alpaca data API."""
        url = f"{self._data_url}/v2/stocks/{ticker}/quotes/latest"
        data = await self._request("GET", url)
        q = data.get("quote", {})
        ts_str = q.get("t", "")
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.utcnow()
        return Quote(
            symbol=ticker,
            bid_price=Decimal(str(q.get("bp", 0))),
            ask_price=Decimal(str(q.get("ap", 0))),
            bid_size=int(q.get("bs", 0)),
            ask_size=int(q.get("as", 0)),
            timestamp=ts,
        )

    async def get_latest_trade(self, ticker: str) -> dict:
        """GET /v2/stocks/{symbol}/trades/latest — returns raw dict."""
        url = f"{self._data_url}/v2/stocks/{ticker}/trades/latest"
        data = await self._request("GET", url)
        return data.get("trade", {})

    async def get_equity_positions(self) -> list[dict]:
        """GET /v2/positions — returns raw list of position dicts."""
        data = await self._request("GET", f"{self._base_url}/v2/positions")
        return data if isinstance(data, list) else []
