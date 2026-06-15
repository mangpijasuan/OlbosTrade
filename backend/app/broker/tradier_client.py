"""
Tradier sandbox broker implementation.
Used during development when IBKR TWS is not running.
Set BROKER=tradier in .env to activate.
"""

from __future__ import annotations


from datetime import date, datetime
from decimal import Decimal

import httpx

from app.broker.broker_interface import (
    AccountSummary,
    BrokerInterface,
    Greeks,
    OptionContract,
    OptionsChain,
    OrderResult,
    Position,
    SpreadOrder,
)
from app.core.config import settings

TRADIER_SANDBOX_BASE = "https://sandbox.tradier.com/v1"
TRADIER_LIVE_BASE = "https://api.tradier.com/v1"


class TradierClient(BrokerInterface):
    """
    Tradier REST API client (sandbox + live).
    Uses httpx for async HTTP. All methods are async.
    """

    def __init__(self) -> None:
        base_url = TRADIER_SANDBOX_BASE if settings.tradier_sandbox else TRADIER_LIVE_BASE
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {settings.tradier_api_key}",
                "Accept": "application/json",
            },
            timeout=15.0,
        )

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Shared GET helper with error handling."""
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    # ── BrokerInterface implementation ──────────────────────────────────────

    async def get_options_chain(self, symbol: str, expiry: str) -> OptionsChain:
        """
        Fetch full options chain from Tradier.
        expiry: 'YYYY-MM-DD'
        """
        data = await self._get(
            "/markets/options/chains",
            params={"symbol": symbol, "expiration": expiry, "greeks": "true"},
        )

        options = data.get("options", {}).get("option", []) or []

        calls: list[OptionContract] = []
        puts: list[OptionContract] = []

        for opt in options:
            greeks_data = opt.get("greeks") or {}
            greeks = Greeks(
                delta=float(greeks_data.get("delta") or 0),
                gamma=float(greeks_data.get("gamma") or 0),
                theta=float(greeks_data.get("theta") or 0),
                vega=float(greeks_data.get("vega") or 0),
                implied_vol=float(greeks_data.get("mid_iv") or 0),
            )
            contract = OptionContract(
                symbol=opt["symbol"],
                underlying=symbol,
                expiration=date.fromisoformat(expiry),
                strike=Decimal(str(opt["strike"])),
                option_type=opt["option_type"],
                bid=Decimal(str(opt.get("bid") or 0)),
                ask=Decimal(str(opt.get("ask") or 0)),
                last=Decimal(str(opt.get("last") or 0)),
                volume=int(opt.get("volume") or 0),
                open_interest=int(opt.get("open_interest") or 0),
                greeks=greeks,
            )
            if opt["option_type"] == "call":
                calls.append(contract)
            else:
                puts.append(contract)

        # Fetch underlying price
        quote_data = await self._get("/markets/quotes", params={"symbols": symbol})
        underlying_price = Decimal(
            str(quote_data.get("quotes", {}).get("quote", {}).get("last") or 0)
        )

        return OptionsChain(
            underlying=symbol,
            expiration=date.fromisoformat(expiry),
            underlying_price=underlying_price,
            calls=calls,
            puts=puts,
            fetched_at=datetime.utcnow(),
        )

    async def get_greeks(
        self, symbol: str, strike: float, expiry: str, option_type: str
    ) -> Greeks:
        """Fetch Greeks for a specific contract by scanning the chain."""
        chain = await self.get_options_chain(symbol, expiry)
        contracts = chain.calls if option_type == "call" else chain.puts
        target = Decimal(str(strike))

        for contract in contracts:
            if contract.strike == target and contract.greeks:
                return contract.greeks

        raise ValueError(
            f"Contract not found: {symbol} {expiry} {strike} {option_type}"
        )

    async def place_order(self, spread: SpreadOrder) -> OrderResult:
        """
        Submit a multi-leg spread order to Tradier.
        Tradier uses their combo order endpoint for spreads.
        """
        # Build leg payload
        payload: dict = {
            "class": "multileg",
            "symbol": spread.underlying,
            "type": spread.order_type.lower(),
            "duration": spread.time_in_force.lower(),
            "price": str(spread.limit_price),
        }
        for i, leg in enumerate(spread.legs):
            payload[f"option_symbol[{i}]"] = leg.symbol
            payload[f"side[{i}]"] = leg.action.lower()
            payload[f"quantity[{i}]"] = str(leg.quantity)

        response = await self._client.post("/accounts/{account_id}/orders", data=payload)
        response.raise_for_status()
        data = response.json().get("order", {})

        return OrderResult(
            order_id=str(data.get("id", "")),
            status=data.get("status", "submitted"),
            message=data.get("status"),
        )

    async def get_positions(self) -> list[Position]:
        """Return open positions from Tradier account."""
        data = await self._get("/accounts/{account_id}/positions")
        raw = data.get("positions", {}).get("position", []) or []
        if isinstance(raw, dict):
            raw = [raw]

        positions = []
        for p in raw:
            positions.append(
                Position(
                    symbol=p["symbol"],
                    underlying=p.get("symbol", "")[:3],
                    strike=Decimal("0"),
                    expiration=date.today(),
                    option_type="call",
                    quantity=int(p.get("quantity", 0)),
                    avg_cost=Decimal(str(p.get("cost_basis", 0))),
                )
            )
        return positions

    async def get_account_summary(self) -> AccountSummary:
        """Return account balances from Tradier."""
        data = await self._get("/accounts/{account_id}/balances")
        balances = data.get("balances", {})

        return AccountSummary(
            account_id=str(balances.get("account_number", "sandbox")),
            net_liquidation=Decimal(str(balances.get("total_equity", 0))),
            cash_balance=Decimal(str(balances.get("total_cash", 0))),
            buying_power=Decimal(str(balances.get("option_buying_power", 0))),
            trading_mode="sandbox" if settings.tradier_sandbox else "live",
        )

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
