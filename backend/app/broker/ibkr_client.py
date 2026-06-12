"""
Interactive Brokers client via ib_insync.
Connects to TWS paper on port 7497 by default.
All methods are async-compatible via ib_insync's asyncio event loop.
"""

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal

from ib_insync import IB, Contract, LimitOrder, Option, Stock

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

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


class IBKRClient(BrokerInterface):
    """
    IBKR broker implementation using ib_insync.
    Paper trading port: 7497 | Live port: 7496
    Gateway paper: 4002  | Gateway live: 4001
    """

    def __init__(self) -> None:
        self.ib = IB()
        self._connected = False

    async def connect(self) -> None:
        """Connect to TWS/Gateway with retry logic (max 3 attempts, 5s delay)."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await self.ib.connectAsync(
                    host=settings.ibkr_host,
                    port=settings.ibkr_port,
                    clientId=settings.ibkr_client_id,
                )
                self._connected = True
                logger.info(
                    "IBKR connected — host=%s port=%s clientId=%s",
                    settings.ibkr_host,
                    settings.ibkr_port,
                    settings.ibkr_client_id,
                )
                return
            except Exception as exc:
                logger.warning(
                    "IBKR connection attempt %d/%d failed: %s",
                    attempt, MAX_RETRIES, exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

        raise ConnectionError(
            f"Failed to connect to IBKR after {MAX_RETRIES} attempts. "
            f"Is TWS/Gateway running on {settings.ibkr_host}:{settings.ibkr_port}?"
        )

    async def disconnect(self) -> None:
        """Gracefully disconnect from TWS/Gateway."""
        if self._connected:
            self.ib.disconnect()
            self._connected = False
            logger.info("IBKR disconnected")

    def _require_connection(self) -> None:
        if not self._connected or not self.ib.isConnected():
            raise ConnectionError("IBKR client is not connected. Call connect() first.")

    # ── BrokerInterface implementation ──────────────────────────────────────

    async def get_options_chain(self, symbol: str, expiry: str) -> OptionsChain:
        """
        Fetch options chain via IBKR's reqSecDefOptParams + reqTickers.
        expiry: 'YYYY-MM-DD'
        """
        self._require_connection()

        expiry_ib = expiry.replace("-", "")  # IBKR uses YYYYMMDD
        underlying = Stock(symbol, "SMART", "USD")
        await self.ib.qualifyContractsAsync(underlying)

        # Fetch chain parameters to get available strikes
        chains = await self.ib.reqSecDefOptParamsAsync(
            symbol, "", underlying.secType, underlying.conId
        )
        target_chain = next(
            (c for c in chains if expiry_ib in c.expirations), None
        )
        if not target_chain:
            raise ValueError(f"No IBKR chain found for {symbol} on {expiry}")

        calls: list[OptionContract] = []
        puts: list[OptionContract] = []

        for option_type in ("C", "P"):
            for strike in sorted(target_chain.strikes):
                opt = Option(symbol, expiry_ib, strike, option_type, "SMART")
                contracts = await self.ib.qualifyContractsAsync(opt)
                if not contracts:
                    continue

                tickers = await self.ib.reqTickersAsync(*contracts)
                for ticker in tickers:
                    g = ticker.modelGreeks
                    greeks = Greeks(
                        delta=float(g.delta or 0) if g else 0.0,
                        gamma=float(g.gamma or 0) if g else 0.0,
                        theta=float(g.theta or 0) if g else 0.0,
                        vega=float(g.vega or 0) if g else 0.0,
                        implied_vol=float(g.impliedVol or 0) if g else 0.0,
                    )
                    contract = OptionContract(
                        symbol=ticker.contract.localSymbol or ticker.contract.symbol,
                        underlying=symbol,
                        expiration=date.fromisoformat(expiry),
                        strike=Decimal(str(strike)),
                        option_type="call" if option_type == "C" else "put",
                        bid=Decimal(str(ticker.bid or 0)),
                        ask=Decimal(str(ticker.ask or 0)),
                        last=Decimal(str(ticker.last or 0)),
                        volume=int(ticker.volume or 0),
                        open_interest=int(ticker.callOpenInterest or ticker.putOpenInterest or 0),
                        greeks=greeks,
                    )
                    if option_type == "C":
                        calls.append(contract)
                    else:
                        puts.append(contract)

        # Underlying price
        under_ticker = await self.ib.reqTickersAsync(underlying)
        underlying_price = Decimal(str(under_ticker[0].last or 0)) if under_ticker else Decimal("0")

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
        """Fetch Greeks for a specific contract."""
        self._require_connection()

        expiry_ib = expiry.replace("-", "")
        opt = Option(symbol, expiry_ib, strike, "C" if option_type == "call" else "P", "SMART")
        contracts = await self.ib.qualifyContractsAsync(opt)
        if not contracts:
            raise ValueError(f"Contract not found: {symbol} {expiry} {strike} {option_type}")

        tickers = await self.ib.reqTickersAsync(*contracts)
        g = tickers[0].modelGreeks if tickers else None
        if not g:
            raise ValueError(f"No Greeks returned for {symbol} {expiry} {strike} {option_type}")

        return Greeks(
            delta=float(g.delta or 0),
            gamma=float(g.gamma or 0),
            theta=float(g.theta or 0),
            vega=float(g.vega or 0),
            implied_vol=float(g.impliedVol or 0),
        )

    async def place_order(self, spread: SpreadOrder) -> OrderResult:
        """
        Submit a combo/spread order to IBKR.
        Uses a ComboLeg bag contract for multi-leg spreads.
        """
        self._require_connection()

        from ib_insync import ComboLeg, Contract as IBContract

        legs = []
        for leg in spread.legs:
            expiry_ib = leg.expiration.strftime("%Y%m%d")
            opt = Option(leg.symbol, expiry_ib, float(leg.strike),
                         "C" if leg.option_type == "call" else "P", "SMART")
            qualified = await self.ib.qualifyContractsAsync(opt)
            if not qualified:
                raise ValueError(f"Could not qualify leg: {leg}")
            combo_leg = ComboLeg(
                conId=qualified[0].conId,
                ratio=leg.quantity,
                action=leg.action,
                exchange="SMART",
            )
            legs.append(combo_leg)

        bag = IBContract()
        bag.symbol = spread.underlying
        bag.secType = "BAG"
        bag.currency = "USD"
        bag.exchange = "SMART"
        bag.comboLegs = legs

        order = LimitOrder(
            action="BUY",
            totalQuantity=1,
            lmtPrice=float(spread.limit_price),
        )
        order.tif = spread.time_in_force

        trade = self.ib.placeOrder(bag, order)
        await asyncio.sleep(1)  # Allow IBKR to process

        return OrderResult(
            order_id=str(trade.order.orderId),
            status="submitted",
            message=str(trade.orderStatus.status),
        )

    async def get_positions(self) -> list[Position]:
        """Return all open positions from IBKR account."""
        self._require_connection()

        ib_positions = await self.ib.reqPositionsAsync()
        positions = []
        for pos in ib_positions:
            if pos.contract.secType != "OPT":
                continue
            c = pos.contract
            positions.append(
                Position(
                    symbol=c.localSymbol or c.symbol,
                    underlying=c.symbol,
                    strike=Decimal(str(c.strike)),
                    expiration=datetime.strptime(c.lastTradeDateOrContractMonth, "%Y%m%d").date(),
                    option_type="call" if c.right == "C" else "put",
                    quantity=int(pos.position),
                    avg_cost=Decimal(str(pos.avgCost)),
                )
            )
        return positions

    async def get_account_summary(self) -> AccountSummary:
        """Return account summary from IBKR."""
        self._require_connection()

        summary = await self.ib.reqAccountSummaryAsync()
        values: dict[str, str] = {item.tag: item.value for item in summary}

        return AccountSummary(
            account_id=values.get("AccountCode", "unknown"),
            net_liquidation=Decimal(values.get("NetLiquidation", "0")),
            cash_balance=Decimal(values.get("TotalCashValue", "0")),
            buying_power=Decimal(values.get("OptionBuyingPower", "0")),
            trading_mode="paper" if settings.ibkr_port in (7497, 4002) else "live",
        )
