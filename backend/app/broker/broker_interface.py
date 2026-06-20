"""
Abstract broker interface + all shared Pydantic v2 models.
Every broker implementation must satisfy this contract exactly.
Swap IBKR ↔ Alpaca by changing BROKER= in .env — nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


# ── Shared Pydantic Models ──────────────────────────────────────────────────

class Greeks(BaseModel):
    """Option Greeks for a single contract."""
    delta: float = Field(description="Directional risk (-1 to 1)")
    gamma: float = Field(description="Rate of delta change")
    theta: float = Field(description="Time decay per day (negative for long options)")
    vega: float = Field(description="Sensitivity to 1% IV change")
    rho: float = Field(default=0.0, description="Sensitivity to interest rate change")
    implied_vol: float = Field(description="Implied volatility as decimal (e.g. 0.25 = 25%)")


class OptionContract(BaseModel):
    """A single row in an options chain."""
    symbol: str
    underlying: str
    expiration: date
    strike: Decimal
    option_type: Literal["call", "put"]
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume: int
    open_interest: int
    greeks: Greeks | None = None


class OptionsChain(BaseModel):
    """Full options chain for one underlying + expiry."""
    underlying: str
    expiration: date
    underlying_price: Decimal
    calls: list[OptionContract]
    puts: list[OptionContract]
    fetched_at: datetime


class SpreadLeg(BaseModel):
    """One leg of a multi-leg spread order."""
    symbol: str
    strike: Decimal
    expiration: date
    option_type: Literal["call", "put"]
    action: Literal["BUY", "SELL"]
    quantity: int


class SpreadOrder(BaseModel):
    """A complete multi-leg options spread order."""
    strategy: str
    underlying: str
    legs: list[SpreadLeg]
    limit_price: Decimal = Field(description="Net credit (positive) or debit (negative)")
    order_type: Literal["LMT", "MKT"] = "LMT"
    time_in_force: Literal["DAY", "GTC"] = "DAY"
    client_order_id: str | None = None


class OrderResult(BaseModel):
    """Result returned after submitting an order.

    ``status`` semantics:
      - ``filled``    — the full requested quantity was filled.
      - ``partial``   — some, but not all, of the requested quantity filled.
                        ``filled_quantity`` / ``remaining_quantity`` describe how
                        much. Callers MUST handle the residual exposure.
      - ``submitted`` — accepted by the broker and still working (no fill yet).
      - ``cancelled`` / ``rejected`` — terminated with no fill.
    """
    order_id: str
    status: Literal["submitted", "filled", "partial", "cancelled", "rejected", "pending"]
    fill_price: Decimal | None = None
    filled_at: datetime | None = None
    filled_quantity: int | None = None
    remaining_quantity: int | None = None
    message: str | None = None


class Position(BaseModel):
    """A live position held in the account."""
    symbol: str
    underlying: str
    strike: Decimal
    expiration: date
    option_type: Literal["call", "put"]
    quantity: int = Field(description="Positive = long, negative = short")
    avg_cost: Decimal
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    greeks: Greeks | None = None


class EquityPosition(BaseModel):
    """A live equity (stock/ETF) position."""
    symbol: str
    quantity: int = Field(description="Positive = long, negative = short")
    avg_cost: Decimal
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    market_value: Decimal | None = None


class AccountSummary(BaseModel):
    """Top-level account snapshot."""
    account_id: str
    net_liquidation: Decimal
    cash_balance: Decimal
    buying_power: Decimal
    day_trades_remaining: int | None = None
    trading_mode: Literal["live", "paper", "sandbox"] = "paper"


class Bar(BaseModel):
    """A single OHLCV bar."""
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class Quote(BaseModel):
    """Latest bid/ask quote for an equity."""
    symbol: str
    bid_price: Decimal
    ask_price: Decimal
    bid_size: int
    ask_size: int
    timestamp: datetime


class EquityOrderResult(BaseModel):
    """Result of an equity order submission."""
    order_id: str
    status: Literal["submitted", "filled", "partial", "cancelled", "rejected", "pending"]
    fill_price: Decimal | None = None
    filled_at: datetime | None = None
    filled_quantity: int | None = None
    remaining_quantity: int | None = None
    message: str | None = None


# ── Abstract Interface ──────────────────────────────────────────────────────

class BrokerInterface(ABC):
    """
    All broker clients must implement this interface.
    No strategy or risk code should ever import a concrete client directly —
    always depend on BrokerInterface.
    """

    @property
    @abstractmethod
    def supports_options(self) -> bool:
        """True if this broker supports options trading."""
        ...

    @property
    @abstractmethod
    def supports_equities(self) -> bool:
        """True if this broker supports equity trading."""
        ...

    @abstractmethod
    async def get_options_chain(self, symbol: str, expiry: str) -> OptionsChain:
        """Fetch the full options chain for a symbol at a given expiry (YYYY-MM-DD)."""
        ...

    @abstractmethod
    async def get_greeks(
        self, symbol: str, strike: float, expiry: str, option_type: str
    ) -> Greeks:
        """Fetch Greeks for a specific contract."""
        ...

    @abstractmethod
    async def place_order(self, spread: SpreadOrder) -> OrderResult:
        """Submit a spread order. Must raise on rejection."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open options positions."""
        ...

    @abstractmethod
    async def get_account_summary(self) -> AccountSummary:
        """Return top-level account figures."""
        ...

    @abstractmethod
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
        """Submit an equity order with optional bracket (stop + take-profit)."""
        ...

    @abstractmethod
    async def get_bars(
        self, ticker: str, timeframe: str = "1Day", limit: int = 100
    ) -> list[Bar]:
        """Fetch OHLCV bars for an equity symbol."""
        ...

    @abstractmethod
    async def get_latest_quote(self, ticker: str) -> Quote:
        """Fetch the latest bid/ask quote for an equity."""
        ...
