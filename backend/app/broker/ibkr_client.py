"""
Interactive Brokers client via ib_insync.
Connects to TWS paper on port 7497 by default.
All methods are async-compatible via ib_insync's asyncio event loop.
"""

from __future__ import annotations


import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from ib_insync import IB, Contract, Index, LimitOrder, Option, Stock

from app.broker.broker_interface import (
    AccountSummary,
    Bar,
    BrokerInterface,
    EquityOrderResult,
    Greeks,
    OptionContract,
    OptionsChain,
    OrderResult,
    Position,
    Quote,
    SpreadOrder,
)
from typing import Literal
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# ── Fill timeout & retry settings (overridden by .env via settings) ────────────
# How long to wait for a fill before cancelling and retrying at a better price.
FILL_TIMEOUT_SECONDS = 60        # Wait up to 60s for the first fill attempt
RETRY_PRICE_STEP = 0.05          # On retry, lower limit by $0.05 (accept less credit)
MAX_ORDER_RETRIES = 2            # Cancel + retry up to this many times

def _fill_timeout() -> int:
    try:
        from app.core.config import settings
        return settings.fill_timeout_seconds
    except Exception:
        return FILL_TIMEOUT_SECONDS

def _retry_step() -> float:
    try:
        from app.core.config import settings
        return settings.retry_price_step
    except Exception:
        return RETRY_PRICE_STEP

def _max_retries() -> int:
    try:
        from app.core.config import settings
        return settings.max_order_retries
    except Exception:
        return MAX_ORDER_RETRIES


class IBKRClient(BrokerInterface):
    """
    IBKR broker implementation using ib_insync.
    Paper trading port: 7497 | Live port: 7496
    Gateway paper: 4002  | Gateway live: 4001
    """

    supports_options: bool = True
    supports_equities: bool = True

    def __init__(self) -> None:
        self.ib = IB()
        self._connected = False
        self._disconnect_hooked = False

    def _on_disconnected(self) -> None:
        """Flip state on a dropped socket so the reconnect loop re-establishes it."""
        self._connected = False
        logger.warning("IBKR socket disconnected — marked for reconnect")

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
                # Register the disconnect handler once so a mid-session socket
                # drop flips _connected and the background loop reconnects.
                if not self._disconnect_hooked:
                    try:
                        self.ib.disconnectedEvent += self._on_disconnected
                        self._disconnect_hooked = True
                    except Exception:
                        pass
                logger.info(
                    "IBKR connected — host=%s port=%s clientId=%s",
                    settings.ibkr_host,
                    settings.ibkr_port,
                    settings.ibkr_client_id,
                )
                # Request delayed market data (type 3 = delayed 15-min, free).
                # Without this, reqTickersAsync returns error 10168 for accounts
                # without a live market data subscription.
                # Type 4 = delayed-frozen: returns last available price when
                # market is closed, so the UI always shows a number.
                #   1 = live (requires subscription)
                #   2 = frozen (last close, requires subscription)
                #   3 = delayed 15-min (free)
                #   4 = delayed-frozen (free, works outside market hours)
                self.ib.reqMarketDataType(4)
                logger.info("IBKR market data type set to 4 (delayed-frozen, free)")
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
            fetched_at=datetime.now(timezone.utc),
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
        Submit a combo/spread order to IBKR with:
          - Real-time status event logging
          - Fill timeout (FILL_TIMEOUT_SECONDS)
          - Cancel + retry at a more aggressive price (up to MAX_ORDER_RETRIES times)

        Credit spreads are submitted as BUY combo orders (we pay a negative net
        debit = collect a credit). limit_price > 0 means net credit received.
        """
        self._require_connection()

        from ib_insync import ComboLeg, Contract as IBContract

        # ── Qualify all legs once (reused across retries) ──────────────────────
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

        # Keep limit_price as the SIGNED net (credit positive / debit negative);
        # the retry loop decrements it to become more marketable. The IBKR wire
        # sign is applied at the LimitOrder below (BAG combos are debit-positive
        # for a BUY, so we send -limit_price).
        limit_price = float(spread.limit_price)
        is_credit = limit_price > 0   # credit can't be repriced past 0 into a debit
        last_trade = None
        _timeout = _fill_timeout()
        _step    = _retry_step()
        _retries = _max_retries()

        is_market = (spread.order_type == "MKT")
        for attempt in range(1, _retries + 2):  # +2: initial + retries
            # Use quantity from SpreadOrder (legs share the same contract count)
            spread_qty = max(1, max(leg.quantity for leg in spread.legs))
            if is_market:
                # Honor MKT (e.g. kill-switch / dispatcher flatten). Previously every
                # order was a LimitOrder, so a "market" flatten became a $0 limit that
                # never filled — leaving naked exposure while logging "flatten complete".
                from ib_insync import MarketOrder
                order = MarketOrder(action="BUY", totalQuantity=spread_qty, tif="DAY")
            else:
                order = LimitOrder(
                    action="BUY",
                    totalQuantity=spread_qty,
                    # IBKR BAG combo is debit-positive for a BUY: send -net so a
                    # credit (positive net) becomes a negative limit. VERIFY ON PAPER.
                    lmtPrice=round(-limit_price, 2),
                    tif="DAY",  # explicit DAY to match IB Gateway order preset (avoids Error 10349 cancel)
                )
            # Allow SpreadOrder to override TIF (e.g. GTC) but default to DAY
            if spread.time_in_force and spread.time_in_force != "DAY":
                order.tif = spread.time_in_force

            logger.info(
                "Submitting spread order (attempt %d/%d): %s limit=%.2f",
                attempt, _retries + 1,
                spread.underlying, limit_price,
            )

            trade = self.ib.placeOrder(bag, order)
            last_trade = trade

            # ── Subscribe to status events for real-time logging ───────────────
            def _on_status(t=trade):
                logger.info(
                    "Order %s — status: %-12s  filled: %s/%s  avg_price: %.4f",
                    t.order.orderId,
                    t.orderStatus.status,
                    t.orderStatus.filled,
                    t.order.totalQuantity,
                    t.orderStatus.avgFillPrice or 0.0,
                )
            trade.statusEvent += _on_status

            def _on_fill(trade_, fill_, holding_=None):
                logger.info(
                    "FILL: order %s — %s x%s @ $%.4f  execution_id=%s",
                    trade_.order.orderId,
                    fill_.contract.localSymbol,
                    fill_.execution.shares,
                    fill_.execution.price,
                    fill_.execution.execId,
                )
            trade.fillEvent += _on_fill

            # ── Wait for fill or timeout ───────────────────────────────────────
            deadline = asyncio.get_event_loop().time() + _timeout
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1)
                status = trade.orderStatus.status
                # Only treat as done on a FULL fill — a partial (filled < total)
                # must not be reported as complete, or the caller stops monitoring
                # while contracts are still working.
                if status == "Filled" and trade.orderStatus.filled >= trade.order.totalQuantity:
                    logger.info(
                        "Order %s filled: %s contracts @ avg $%.4f",
                        trade.order.orderId,
                        trade.orderStatus.filled,
                        trade.orderStatus.avgFillPrice,
                    )
                    return OrderResult(
                        order_id=str(trade.order.orderId),
                        status="filled",
                        fill_price=__import__("decimal").Decimal(
                            str(round(trade.orderStatus.avgFillPrice, 4))
                        ),
                        filled_at=datetime.now(timezone.utc),
                        message=f"Filled {trade.orderStatus.filled} contracts @ "
                                f"${trade.orderStatus.avgFillPrice:.4f}",
                    )
                if status in ("Cancelled", "Rejected", "Inactive"):
                    logger.warning(
                        "Order %s %s — not retrying", trade.order.orderId, status
                    )
                    return OrderResult(
                        order_id=str(trade.order.orderId),
                        status="rejected" if status == "Rejected" else "cancelled",
                        message=status,
                    )

            # ── Timeout: cancel, CONFIRM the cancel, then decide ──────────────
            # Confirming avoids a duplicate fill: if we cancel-then-resubmit while
            # the original is mid-fill, both could fill.
            self.ib.cancelOrder(trade.order)
            cancel_outcome = await self._await_cancel(trade)
            if cancel_outcome == "filled":
                logger.info(
                    "Order %s filled during cancel — returning fill (no retry)",
                    trade.order.orderId,
                )
                return OrderResult(
                    order_id=str(trade.order.orderId),
                    status="filled",
                    fill_price=__import__("decimal").Decimal(
                        str(round(trade.orderStatus.avgFillPrice, 4))
                    ),
                    filled_at=datetime.now(timezone.utc),
                    message=f"Filled {trade.orderStatus.filled} contracts @ "
                            f"${trade.orderStatus.avgFillPrice:.4f}",
                )

            # Market flatten orders have no price to improve — do not loop.
            if is_market:
                logger.error("Market order %s did not fill within timeout", trade.order.orderId)
                break
            if attempt <= _retries:
                # Decrement always = more marketable: a credit gives up edge
                # toward 0; a debit (negative) pays more (more negative).
                limit_price = round(limit_price - _step, 2)
                logger.warning(
                    "Order %s timed out — retrying at more aggressive limit (→ %.2f)",
                    trade.order.orderId, limit_price,
                )
                # Only a credit has a hard floor: don't reprice it into a debit.
                if is_credit and limit_price <= 0:
                    logger.error("Credit reached zero — aborting retries")
                    break
            else:
                logger.error("Order %s timed out on final attempt", trade.order.orderId)

        # All attempts exhausted
        order_id = str(last_trade.order.orderId) if last_trade else "unknown"
        return OrderResult(
            order_id=order_id,
            status="cancelled",
            message=f"No fill after {_retries + 1} attempts",
        )

    async def _await_cancel(self, trade, timeout: float = 5.0) -> str:
        """
        Wait for a cancel to be confirmed by IBKR.

        Returns 'cancelled' once the order reaches a terminal cancelled state,
        'filled' if it fully filled before the cancel landed (caller must NOT
        retry in that case), or 'unknown' on timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
            st = trade.orderStatus.status
            if st in ("Cancelled", "ApiCancelled", "Inactive"):
                return "cancelled"
            if st == "Filled" and trade.orderStatus.filled >= trade.order.totalQuantity:
                return "filled"
        logger.warning(
            "Cancel of order %s not confirmed within %.0fs", trade.order.orderId, timeout
        )
        return "unknown"

    async def get_positions(self) -> list[Position]:
        """Return all open positions from IBKR account."""
        self._require_connection()

        ib_positions = await self.ib.reqPositionsAsync()
        positions = []
        for pos in ib_positions:
            c = pos.contract
            if c.secType not in ("OPT", "STK", "ETF"):
                continue  # skip futures, FX, bonds, etc.
            if c.secType == "OPT":
                positions.append(
                    Position(
                        symbol=c.localSymbol or c.symbol,
                        underlying=c.symbol,
                        strike=Decimal(str(c.strike or 0)),
                        expiration=datetime.strptime(
                            c.lastTradeDateOrContractMonth, "%Y%m%d"
                        ).date() if c.lastTradeDateOrContractMonth else date.today(),
                        option_type="call" if c.right == "C" else "put",
                        quantity=int(pos.position),
                        avg_cost=Decimal(str(pos.avgCost)),
                    )
                )
            else:
                # Equity / ETF — use synthetic option_type and strike=0
                positions.append(
                    Position(
                        symbol=c.symbol,
                        underlying=c.symbol,
                        strike=Decimal("0"),
                        expiration=date.today(),
                        option_type="call",       # placeholder — not used for equities
                        quantity=int(pos.position),
                        avg_cost=Decimal(str(pos.avgCost)),
                    )
                )
        return positions

    async def get_equity_positions(self):
        """Return only equity (STK/ETF) positions — delegates to get_positions()."""
        from app.broker.broker_interface import EquityPosition
        all_positions = await self.get_positions()
        result = []
        for pos in all_positions:
            if pos.strike == __import__("decimal").Decimal("0"):  # equity sentinel
                result.append(EquityPosition(
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    avg_cost=pos.avg_cost,
                ))
        return result

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
        """Submit an equity order via IBKR."""
        self._require_connection()
        stock = Stock(ticker, "SMART", "USD")
        await self.ib.qualifyContractsAsync(stock)

        from ib_insync import MarketOrder, StopOrder
        ib_action = side
        exit_action = "SELL" if side == "BUY" else "BUY"

        def _entry():
            if order_type == "market":
                return MarketOrder(action=ib_action, totalQuantity=qty, tif="DAY")
            # explicit DAY to match IB Gateway order preset — avoids Error 10349 cancel
            return LimitOrder(action=ib_action, totalQuantity=qty,
                              lmtPrice=limit_price or 0.0, tif="DAY")

        if stop or take_profit:
            # Build a REAL bracket: parent entry + attached protective children.
            # The previous code set order.takeProfitPrice / order.stopLossPrice,
            # which are not ib_insync Order fields — so trades the system believed
            # were stop-protected actually had NO stop at the broker.
            parent = _entry()
            parent.orderId = self.ib.client.getReqId()
            parent.transmit = False
            children = []
            if take_profit:
                tp = LimitOrder(exit_action, qty, round(float(take_profit), 2), tif="GTC")
                tp.parentId = parent.orderId
                tp.transmit = False
                children.append(tp)
            if stop:
                sl = StopOrder(exit_action, qty, round(float(stop), 2), tif="GTC")
                sl.parentId = parent.orderId
                sl.transmit = True   # last child transmits the whole bracket
                children.append(sl)
            else:
                children[-1].transmit = True  # only a take-profit child → it transmits

            logger.info(
                "Submitting equity BRACKET: %s %s x%d entry=%s stop=%s tp=%s",
                side, ticker, qty,
                f"${limit_price:.2f}" if limit_price else "MKT", stop, take_profit,
            )
            trade = self.ib.placeOrder(stock, parent)
            for child in children:
                self.ib.placeOrder(stock, child)
        else:
            order = _entry()
            logger.info("Submitting equity order: %s %s x%d @ %s",
                        side, ticker, qty, f"${limit_price:.2f}" if limit_price else "MKT")
            trade = self.ib.placeOrder(stock, order)

        # ── Real-time status logging ───────────────────────────────────────────
        def _on_status(t=trade):
            logger.info(
                "Equity order %s — status: %-12s  filled: %s/%s  avg: %.4f",
                t.order.orderId,
                t.orderStatus.status,
                t.orderStatus.filled,
                t.order.totalQuantity,
                t.orderStatus.avgFillPrice or 0.0,
            )
        trade.statusEvent += _on_status

        def _on_fill(trade_, fill_, holding_=None):
            logger.info(
                "EQUITY FILL: order %s — %s x%s @ $%.4f",
                trade_.order.orderId,
                fill_.contract.symbol,
                fill_.execution.shares,
                fill_.execution.price,
            )
        trade.fillEvent += _on_fill

        # ── Wait for fill (market orders fill fast; limit orders may take time) ─
        _timeout = _fill_timeout()
        deadline = asyncio.get_event_loop().time() + _timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1)
            status = trade.orderStatus.status
            if status == "Filled" and trade.orderStatus.filled >= trade.order.totalQuantity:
                return EquityOrderResult(
                    order_id=str(trade.order.orderId),
                    status="filled",
                    fill_price=__import__("decimal").Decimal(
                        str(round(trade.orderStatus.avgFillPrice, 4))
                    ),
                    filled_at=datetime.now(timezone.utc),
                    message=f"Filled {trade.orderStatus.filled} shares @ "
                            f"${trade.orderStatus.avgFillPrice:.4f}",
                )
            if status in ("Cancelled", "Rejected", "Inactive"):
                return EquityOrderResult(
                    order_id=str(trade.order.orderId),
                    status="rejected" if status == "Rejected" else "cancelled",
                    message=status,
                )

        # Timed out — return submitted status (order stays working at IBKR)
        logger.warning(
            "Equity order %s still pending after %ds — returning submitted status",
            trade.order.orderId, _timeout,
        )
        return EquityOrderResult(
            order_id=str(trade.order.orderId),
            status="submitted",
            message=f"Order working — no fill after {_timeout}s",
        )

    async def get_bars(
        self, ticker: str, timeframe: str = "1 day", limit: int = 100,
        end_date: str = "",
    ) -> list[Bar]:
        """
        Fetch OHLCV daily bars from IBKR historical data.

        Args:
            ticker:   Equity symbol
            timeframe: Ignored (always 1 day)
            limit:    Number of calendar days to look back
            end_date: End date "YYYY-MM-DD" (default = today / latest available)
        """
        self._require_connection()
        stock = Stock(ticker, "SMART", "USD")
        await self.ib.qualifyContractsAsync(stock)

        # Format end date for IBKR: "YYYYMMDD 23:59:59" or "" for latest
        end_dt = ""
        if end_date:
            end_dt = end_date.replace("-", "") + " 23:59:59"

        bars_data = await self.ib.reqHistoricalDataAsync(
            stock,
            endDateTime=end_dt,
            durationStr=f"{limit} D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
        )
        result = []
        for b in bars_data:
            result.append(Bar(
                timestamp=datetime.strptime(str(b.date), "%Y-%m-%d"),
                open=Decimal(str(b.open)),
                high=Decimal(str(b.high)),
                low=Decimal(str(b.low)),
                close=Decimal(str(b.close)),
                volume=int(b.volume) if (b.volume == b.volume) else 0,  # guard NaN
            ))
        return result

    async def get_index_bars(self, symbol: str, exchange: str = "CBOE", limit: int = 60) -> list[Bar]:
        """
        Fetch historical bars for an index (e.g. VIX on CBOE).
        Uses secType=IND instead of STK — required for $VIX, $SPX, etc.
        """
        self._require_connection()
        contract = Index(symbol, exchange, "USD")
        await self.ib.qualifyContractsAsync(contract)
        bars_data = await self.ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=f"{limit} D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
        )
        result = []
        for b in bars_data:
            result.append(Bar(
                timestamp=datetime.strptime(str(b.date), "%Y-%m-%d"),
                open=Decimal(str(b.open)),
                high=Decimal(str(b.high)),
                low=Decimal(str(b.low)),
                close=Decimal(str(b.close)),
                volume=int(b.volume) if (b.volume == b.volume) else 0,
            ))
        return result

    async def get_latest_quote(self, ticker: str) -> Quote:
        """Fetch latest bid/ask quote for an equity from IBKR."""
        self._require_connection()
        stock = Stock(ticker, "SMART", "USD")
        await self.ib.qualifyContractsAsync(stock)
        tickers = await self.ib.reqTickersAsync(stock)
        t = tickers[0] if tickers else None
        if not t:
            raise ValueError(f"No quote returned for {ticker}")
        def _safe_decimal(v) -> Decimal:
            """Convert IBKR float to Decimal, treating NaN/None as 0."""
            if v is None:
                return Decimal("0")
            try:
                f = float(v)
                return Decimal("0") if f != f else Decimal(str(f))  # NaN check
            except Exception:
                return Decimal("0")

        def _safe_int(v) -> int:
            """Convert IBKR float size to int, treating NaN/None as 0."""
            if v is None:
                return 0
            try:
                f = float(v)
                return 0 if f != f else int(f)  # NaN check
            except Exception:
                return 0

        return Quote(
            symbol=ticker,
            bid_price=_safe_decimal(t.bid),
            ask_price=_safe_decimal(t.ask),
            bid_size=_safe_int(t.bidSize),
            ask_size=_safe_int(t.askSize),
            timestamp=datetime.now(timezone.utc),
        )

    async def get_account_summary(self) -> AccountSummary:
        """
        Return account summary from IBKR.
        Uses reqAccountValuesAsync (one-shot, no persistent subscription)
        to avoid IBKR error 322 (subscription accumulation).
        """
        self._require_connection()

        # accountValues() returns cached values from the TWS account subscription (no new request).
        # reqAccountSummaryAsync opens a persistent subscription — avoid calling it repeatedly.
        account_values = self.ib.accountValues()
        if not account_values:
            # First call: subscribe once, grab values, then cancel subscription
            account_id_temp = (self.ib.managedAccounts() or [""])[0]
            await self.ib.reqAccountUpdatesAsync(True, account_id_temp)
            account_values = self.ib.accountValues()
            await self.ib.reqAccountUpdatesAsync(False, account_id_temp)

        values: dict[str, str] = {}
        account_id = (self.ib.managedAccounts() or ["unknown"])[0]
        for v in account_values:
            if v.currency in ("USD", "BASE", ""):
                values[v.tag] = v.value

        return AccountSummary(
            account_id=account_id,
            net_liquidation=Decimal(values.get("NetLiquidation", "0") or "0"),
            cash_balance=Decimal(values.get("TotalCashValue", "0") or "0"),
            buying_power=Decimal(values.get("BuyingPower", values.get("OptionBuyingPower", "0")) or "0"),
            trading_mode="paper" if settings.ibkr_port in (7497, 4002) else "live",
        )
