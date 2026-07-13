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
from typing import Dict, List, Literal, Tuple

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
    SpreadLeg,
    SpreadOrder,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# ── Fill timeout & retry settings (overridden by .env via settings) ────────────
# How long to wait for a fill before cancelling and retrying at a better price.
FILL_TIMEOUT_SECONDS = 60        # Wait up to 60s for the first fill attempt
RETRY_PRICE_STEP = 0.05          # On retry, lower limit by $0.05 (accept less credit)
MAX_ORDER_RETRIES = 2            # Cancel + retry up to this many times

# How long to wait for the Gateway to acknowledge a bracket's parent order
# before submitting its children. The children reference the parent via
# parentId, and IBKR rejects them with "Error 135: Can't find order with id"
# if they arrive before the Gateway has registered the parent -- this bounds
# that wait rather than racing it.
BRACKET_ACK_TIMEOUT_SECONDS = 3.0

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

        calls: List[OptionContract] = []
        puts: List[OptionContract] = []

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

    @staticmethod
    def _combo_sizing(legs: List[SpreadLeg]) -> Tuple[int, List[int]]:
        """
        Convert absolute per-leg contract counts into IB combo terms: a single
        ``totalQuantity`` (the number of spreads) plus an integer ratio per leg.

        Example: legs of 5/5 → ``(5, [1, 1])``; legs of 5/10 → ``(5, [1, 2])``.

        This prevents the classic combo sizing bug where ``totalQuantity`` is set
        to the per-leg quantity AND each combo leg ratio is also set to the
        per-leg quantity — which sends quantity² contracts per leg.
        """
        from functools import reduce
        from math import gcd

        quantities = [max(1, int(leg.quantity)) for leg in legs]
        spread_qty = reduce(gcd, quantities)
        if spread_qty <= 0:
            spread_qty = 1
        ratios = [q // spread_qty for q in quantities]
        return spread_qty, ratios

    async def _await_order(self, trade, total_qty: int, timeout: int) -> Tuple[str, int, float]:
        """
        Poll an order until it fully fills, terminates, or the timeout expires.

        Returns ``(outcome, filled_qty, avg_price)`` where ``outcome`` is one of:
          - ``"filled"``    — full quantity filled
          - ``"partial"``   — terminated (cancelled/rejected) with a partial fill
          - ``"cancelled"`` / ``"rejected"`` — terminated with no fill
          - ``"timeout"``   — still working when the timeout elapsed (``filled_qty``
                              may be > 0, i.e. a partial that is still working)
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        cancel_states = {"Cancelled", "ApiCancelled", "Inactive"}
        while loop.time() < deadline:
            await asyncio.sleep(1)
            st = trade.orderStatus
            status = st.status
            filled = int(st.filled or 0)
            avg = float(st.avgFillPrice or 0.0)
            if status == "Filled" or (total_qty and filled >= total_qty):
                return "filled", filled, avg
            if status == "Rejected":
                return ("partial" if filled > 0 else "rejected"), filled, avg
            if status in cancel_states:
                return ("partial" if filled > 0 else "cancelled"), filled, avg
        st = trade.orderStatus
        return "timeout", int(st.filled or 0), float(st.avgFillPrice or 0.0)

    async def place_order(self, spread: SpreadOrder) -> OrderResult:
        """
        Submit an options order to IBKR as a SINGLE order (never legged out):
          - 1 leg  → a plain Option order
          - >1 leg → one BAG combo order containing every leg

        Honours ``spread.order_type``:
          - ``"MKT"`` → MarketOrder (used by the kill switch to flatten at any
            price). No price retries — a working market order is left live.
          - ``"LMT"`` → LimitOrder with cancel-and-retry at a more aggressive
            price (up to MAX_ORDER_RETRIES).

        Combo limit-price sign convention: ``spread.limit_price`` is a net credit
        when positive / net debit when negative. A combo is submitted as a BUY of
        the BAG, so the IB limit price is the *net price paid* = ``-limit_price``
        (a credit is a negative price to pay). Single-leg orders use the leg's own
        action and price as-is.

        Partial fills are reported explicitly via ``OrderResult.status == "partial"``
        with ``filled_quantity`` / ``remaining_quantity`` — they are NEVER reported
        as a clean fill.
        """
        self._require_connection()

        from ib_insync import ComboLeg, Contract as IBContract, MarketOrder

        is_market = spread.order_type == "MKT"

        # ── Qualify every leg once (reused across retries) ─────────────────────
        qualified: List[Tuple[SpreadLeg, Contract]] = []
        for leg in spread.legs:
            expiry_ib = leg.expiration.strftime("%Y%m%d")
            opt = Option(leg.symbol, expiry_ib, float(leg.strike),
                         "C" if leg.option_type == "call" else "P", "SMART")
            q = await self.ib.qualifyContractsAsync(opt)
            if not q:
                raise ValueError(f"Could not qualify leg: {leg}")
            qualified.append((leg, q[0]))

        if not qualified:
            raise ValueError("Cannot place an order with no legs")

        spread_qty, ratios = self._combo_sizing(spread.legs)
        single_leg = len(qualified) == 1

        # ── Build the order contract ───────────────────────────────────────────
        if single_leg:
            leg, contract = qualified[0]
            order_action = leg.action          # BUY or SELL the single option
        else:
            combo_legs = []
            for (leg, qc), ratio in zip(qualified, ratios):
                combo_legs.append(ComboLeg(
                    conId=qc.conId,
                    ratio=ratio,
                    action=leg.action,
                    exchange="SMART",
                ))
            contract = IBContract()
            contract.symbol = spread.underlying
            contract.secType = "BAG"
            contract.currency = "USD"
            contract.exchange = "SMART"
            contract.comboLegs = combo_legs
            order_action = "BUY"               # combo direction encoded in legs

        total_qty = spread_qty
        # explicit DAY default matches the IB Gateway preset (avoids Error 10349)
        tif = spread.time_in_force or "DAY"

        def _build_order(net_price: float):
            if is_market:
                o = MarketOrder(action=order_action, totalQuantity=total_qty)
                o.tif = tif
                return o
            lmt = round(net_price if single_leg else -net_price, 2)
            return LimitOrder(action=order_action, totalQuantity=total_qty,
                              lmtPrice=lmt, tif=tif)

        limit_price = float(spread.limit_price)
        last_trade = None
        _timeout = _fill_timeout()
        _step = _retry_step()
        _retries = 0 if is_market else _max_retries()

        for attempt in range(1, _retries + 2):  # +1: initial; +N retries (LMT only)
            order = _build_order(limit_price)
            logger.info(
                "Submitting %s %s order (attempt %d/%d): %s qty=%d%s",
                "single-leg" if single_leg else "combo",
                "MKT" if is_market else "LMT",
                attempt, _retries + 1, spread.underlying, total_qty,
                "" if is_market else f" net_limit={limit_price:.2f}",
            )

            trade = self.ib.placeOrder(contract, order)
            last_trade = trade

            # ── Real-time status + fill event logging ──────────────────────────
            def _on_status(t=trade):
                logger.info(
                    "Order %s — status: %-12s  filled: %s/%s  avg_price: %.4f",
                    t.order.orderId, t.orderStatus.status,
                    t.orderStatus.filled, t.order.totalQuantity,
                    t.orderStatus.avgFillPrice or 0.0,
                )
            trade.statusEvent += _on_status

            def _on_fill(trade_, fill_, holding_=None):
                logger.info(
                    "FILL: order %s — %s x%s @ $%.4f  execution_id=%s",
                    trade_.order.orderId, fill_.contract.localSymbol,
                    fill_.execution.shares, fill_.execution.price,
                    fill_.execution.execId,
                )
            trade.fillEvent += _on_fill

            outcome, filled, avg = await self._await_order(trade, total_qty, _timeout)

            # ── Fully filled ───────────────────────────────────────────────────
            if outcome == "filled":
                logger.info("Order %s fully filled: %d @ avg $%.4f",
                            trade.order.orderId, filled, avg)
                return OrderResult(
                    order_id=str(trade.order.orderId),
                    status="filled",
                    fill_price=Decimal(str(round(avg, 4))),
                    filled_at=datetime.now(timezone.utc),
                    filled_quantity=filled,
                    remaining_quantity=0,
                    message=f"Filled {filled} @ ${avg:.4f}",
                )

            # ── Partial fill — cancel the remainder and report it explicitly ───
            if outcome == "partial":
                logger.warning(
                    "Order %s PARTIAL fill: %d/%d filled — cancelling remainder, "
                    "not retrying (would double the filled portion)",
                    trade.order.orderId, filled, total_qty,
                )
                self.ib.cancelOrder(trade.order)
                await asyncio.sleep(1)
                return OrderResult(
                    order_id=str(trade.order.orderId),
                    status="partial",
                    fill_price=Decimal(str(round(avg, 4))) if filled else None,
                    filled_at=datetime.now(timezone.utc) if filled else None,
                    filled_quantity=filled,
                    remaining_quantity=max(0, total_qty - filled),
                    message=f"Partial fill {filled}/{total_qty} @ ${avg:.4f}",
                )

            # ── Terminated with no fill ────────────────────────────────────────
            if outcome in ("cancelled", "rejected"):
                logger.warning("Order %s %s — not retrying",
                               trade.order.orderId, outcome)
                return OrderResult(
                    order_id=str(trade.order.orderId),
                    status=outcome,
                    filled_quantity=0,
                    remaining_quantity=total_qty,
                    message=outcome,
                )

            # ── Timeout (outcome == "timeout") ─────────────────────────────────
            if filled > 0:
                # Still working but partially filled — cancel remainder, report partial.
                logger.warning(
                    "Order %s timed out PARTIALLY filled: %d/%d — cancelling remainder",
                    trade.order.orderId, filled, total_qty,
                )
                self.ib.cancelOrder(trade.order)
                await asyncio.sleep(1)
                return OrderResult(
                    order_id=str(trade.order.orderId),
                    status="partial",
                    fill_price=Decimal(str(round(avg, 4))),
                    filled_at=datetime.now(timezone.utc),
                    filled_quantity=filled,
                    remaining_quantity=max(0, total_qty - filled),
                    message=f"Partial fill {filled}/{total_qty} @ ${avg:.4f} (timeout)",
                )

            if is_market:
                # A market order with no fill is still working (e.g. market closed).
                # Leave it live — cancelling a flatten could strand naked risk.
                logger.warning(
                    "Market order %s still working after %ds — leaving it live",
                    trade.order.orderId, _timeout,
                )
                return OrderResult(
                    order_id=str(trade.order.orderId),
                    status="submitted",
                    filled_quantity=0,
                    remaining_quantity=total_qty,
                    message=f"Market order working — no fill after {_timeout}s",
                )

            # LMT timeout with no fill → cancel and retry at a better net price
            if attempt <= _retries:
                new_price = round(limit_price - _step, 2)
                logger.warning(
                    "Order %s timed out after %ds — cancelling and retrying at "
                    "lower net limit (%.2f → %.2f)",
                    trade.order.orderId, _timeout, limit_price, new_price,
                )
                self.ib.cancelOrder(trade.order)
                await asyncio.sleep(2)  # let cancel propagate
                limit_price = new_price
                if limit_price <= 0:
                    logger.error("Net limit reached zero — aborting retries")
                    break
            else:
                logger.error("Order %s timed out on final attempt — cancelling",
                             trade.order.orderId)
                self.ib.cancelOrder(trade.order)
                await asyncio.sleep(2)

        # All attempts exhausted with no fill
        order_id = str(last_trade.order.orderId) if last_trade else "unknown"
        return OrderResult(
            order_id=order_id,
            status="cancelled",
            filled_quantity=0,
            remaining_quantity=total_qty,
            message=f"No fill after {_retries + 1} attempt(s)",
        )

    async def get_positions(self) -> List[Position]:
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
        limit_price: Optional[float] = None,
        stop: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> EquityOrderResult:
        """Submit an equity order via IBKR."""
        self._require_connection()
        stock = Stock(ticker, "SMART", "USD")
        await self.ib.qualifyContractsAsync(stock)

        from ib_insync import MarketOrder, StopOrder

        ib_action = side

        def _build_entry() -> object:
            if order_type == "market":
                return MarketOrder(action=ib_action, totalQuantity=qty, tif="DAY")
            # explicit DAY to match IB Gateway order preset — avoids Error 10349 cancel
            return LimitOrder(action=ib_action, totalQuantity=qty,
                              lmtPrice=limit_price or 0.0, tif="DAY")

        # A stop and/or take-profit means a bracket: a parent entry order with
        # OCO child exit orders attached via parentId. The previous code set
        # `order.takeProfitPrice` / `order.stopLossPrice` attributes that
        # ib_insync ignores entirely — so protective exits NEVER reached IBKR.
        use_bracket = (stop is not None) or (take_profit is not None)

        if use_bracket:
            exit_action = "SELL" if ib_action == "BUY" else "BUY"
            parent_id = self.ib.client.getReqId()

            parent = _build_entry()
            parent.orderId = parent_id
            parent.transmit = False   # hold until all children are queued

            children = []
            if take_profit:
                tp = LimitOrder(action=exit_action, totalQuantity=qty,
                                lmtPrice=round(float(take_profit), 2), tif="GTC")
                tp.orderId = self.ib.client.getReqId()
                tp.parentId = parent_id
                # transmit the whole bracket on the last child only
                tp.transmit = stop is None
                children.append(tp)
            if stop:
                sl = StopOrder(action=exit_action, totalQuantity=qty,
                               stopPrice=round(float(stop), 2), tif="GTC")
                sl.orderId = self.ib.client.getReqId()
                sl.parentId = parent_id
                sl.transmit = True   # last leg fires the entire bracket
                children.append(sl)

            logger.info(
                "Submitting equity BRACKET: %s %s x%d @ %s | TP=%s SL=%s",
                side, ticker, qty,
                f"${limit_price:.2f}" if limit_price else "MKT",
                f"${take_profit:.2f}" if take_profit else "—",
                f"${stop:.2f}" if stop else "—",
            )
            trade = self.ib.placeOrder(stock, parent)
            # Gateway registration of the parent is asynchronous — submitting
            # the children immediately can beat it there, and IBKR rejects
            # both with "Error 135: Can't find order with id" (parentId not
            # yet recognized), leaving the entry order dangling with no
            # protective exits attached. Wait for the parent to reach an
            # acknowledged status (or a bounded timeout) before firing the
            # bracket's children.
            ack_deadline = asyncio.get_event_loop().time() + BRACKET_ACK_TIMEOUT_SECONDS
            while (
                not trade.orderStatus.status
                and asyncio.get_event_loop().time() < ack_deadline
            ):
                await asyncio.sleep(0.05)
            if not trade.orderStatus.status:
                logger.warning(
                    "Bracket parent %s %s not acknowledged after %.0fs — "
                    "submitting children anyway (may hit Error 135)",
                    ticker, parent.orderId, BRACKET_ACK_TIMEOUT_SECONDS,
                )
            for child in children:
                self.ib.placeOrder(stock, child)
        else:
            logger.info("Submitting equity order: %s %s x%d @ %s",
                        side, ticker, qty, f"${limit_price:.2f}" if limit_price else "MKT")
            trade = self.ib.placeOrder(stock, _build_entry())

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
            if status in ("Filled", "Submitted") and trade.orderStatus.filled > 0:
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
    ) -> List[Bar]:
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

    async def get_index_bars(self, symbol: str, exchange: str = "CBOE", limit: int = 60) -> List[Bar]:
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

        values: Dict[str, str] = {}
        account_id = (self.ib.managedAccounts() or ["unknown"])[0]
        for v in account_values:
            if v.currency in ("USD", "BASE", ""):
                values[v.tag] = v.value

        def _dec(*tags: str) -> Decimal | None:
            for t in tags:
                v = values.get(t)
                if v not in (None, ""):
                    return Decimal(v)
            return None

        return AccountSummary(
            account_id=account_id,
            net_liquidation=Decimal(values.get("NetLiquidation", "0") or "0"),
            cash_balance=Decimal(values.get("TotalCashValue", "0") or "0"),
            buying_power=Decimal(values.get("BuyingPower", values.get("OptionBuyingPower", "0")) or "0"),
            trading_mode="paper" if settings.ibkr_port in (7497, 4002) else "live",
            maintenance_margin=_dec("MaintMarginReq", "FullMaintMarginReq"),
            excess_liquidity=_dec("ExcessLiquidity", "FullExcessLiquidity"),
            init_margin=_dec("InitMarginReq", "FullInitMarginReq"),
        )
