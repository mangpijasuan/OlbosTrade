"""
Abstract broker interface + all shared Pydantic v2 models.
Every broker implementation must satisfy this contract exactly.
Swap IBKR ↔ Tradier by changing BROKER= in .env — nothing else changes.
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
    """Result returned after submitting an order."""
    order_id: str
    status: Literal["submitted", "filled", "cancelled", "rejected", "pending"]
    fill_price: Decimal | None = None
    filled_at: datetime | None = None
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


class AccountSummary(BaseModel):
    """Top-level account snapshot."""
    account_id: str
    net_liquidation: Decimal
    cash_balance: Decimal
    buying_power: Decimal
    day_trades_remaining: int | None = None
    trading_mode: Literal["live", "paper", "sandbox"] = "paper"


# ── Abstract Interface ──────────────────────────────────────────────────────

class BrokerInterface(ABC):
    """
    All broker clients must implement this interface.
    No strategy or risk code should ever import a concrete client directly —
    always depend on BrokerInterface.
    """

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
        """Return all currently open positions."""
        ...

    @abstractmethod
    async def get_account_summary(self) -> AccountSummary:
        """Return top-level account figures."""
        ...
