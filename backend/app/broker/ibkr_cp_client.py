"""
Interactive Brokers — Client Portal Web API broker client.

This talks to the locally-running Client Portal Gateway (``clientportal.gw``) over
its REST API (default ``https://localhost:5000/v1/api``) instead of the TWS/IB
Gateway socket used by ``ibkr_client.py`` (ib_insync). Select it with
``BROKER=ibkr`` and ``IBKR_CONNECTION=clientportal`` (the default).

Auth model: the gateway handles login. A human logs in once in a browser at
``<base>/sso/Dispatcher``; this client validates/keeps the session alive
(``/iserver/auth/status`` + ``/tickle``) and never handles credentials itself.

Order-safety semantics mirror the TWS client:
  - MKT vs LMT honoured per ``SpreadOrder.order_type``.
  - Multi-leg spreads are sent as ONE combo (``conidex``), never legged out.
  - Combo ratios are normalized (GCD); ``quantity`` is the number of spreads.
  - A credit (``limit_price`` > 0) is submitted as a negative net combo price.
  - Partial fills are reported explicitly (``status="partial"``), never as a
    clean fill.

NOTE: order placement could not be exercised against a live gateway in CI, so the
request/response shapes are covered by unit tests with a mocked transport. Smoke
test against a real gateway before live trading.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import reduce
from math import gcd
from typing import Any, Literal

import httpx

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

# Client Portal market-data snapshot field codes.
F_LAST, F_BID, F_ASK_SIZE, F_ASK, F_BID_SIZE = "31", "84", "85", "86", "88"
F_DELTA, F_GAMMA, F_THETA, F_VEGA, F_IV = "7308", "7309", "7310", "7311", "7283"

_TERMINAL_CANCEL = {"Cancelled", "ApiCancelled", "Inactive", "PendingCancel"}


def _num(value: Any) -> float:
    """Parse a CP numeric that may be a string with markers (e.g. 'C123.4', '1,234')."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    # Strip a leading non-numeric marker such as the 'C' close indicator on field 31.
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(_num(value)))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _amount(value: Any) -> Decimal:
    """CP summary values are often ``{"amount": 123.4, "currency": "USD"}``."""
    if isinstance(value, dict):
        return _dec(value.get("amount", value.get("value", 0)))
    return _dec(value)


def _combo_sizing(legs: list[SpreadLeg]) -> tuple[int, list[int]]:
    """Number of spreads (GCD of leg quantities) + normalized per-leg ratios."""
    quantities = [max(1, int(leg.quantity)) for leg in legs]
    spread_qty = reduce(gcd, quantities)
    if spread_qty <= 0:
        spread_qty = 1
    return spread_qty, [q // spread_qty for q in quantities]


class IBKRClientPortalClient(BrokerInterface):
    """IBKR broker implementation backed by the Client Portal Web API."""

    supports_options: bool = True
    supports_equities: bool = True

    def __init__(self) -> None:
        self._base = settings.ibkr_cp_base_url.rstrip("/")
        self._verify = settings.ibkr_cp_verify_ssl
        self._account_id: str | None = settings.ibkr_account_id or None
        self._connected = False
        self._conid_cache: dict[str, int] = {}
        # Tests may inject an httpx transport (e.g. httpx.MockTransport).
        self._transport: httpx.BaseTransport | None = None

    # ── HTTP plumbing ───────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        async with httpx.AsyncClient(
            verify=self._verify, timeout=20.0, transport=self._transport
        ) as client:
            resp = await client.request(method, f"{self._base}{path}", **kwargs)
            resp.raise_for_status()
            if not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError:
                return {}

    def _require_connection(self) -> None:
        if not self._connected:
            raise ConnectionError(
                "IBKR Client Portal client is not connected. Call connect() first "
                "(and ensure the gateway is authenticated in a browser)."
            )

    # ── Session / auth ────────────────────────────────────────────────────────

    async def _auth_status(self) -> dict:
        # /iserver/auth/status is documented as POST but most gateway builds also
        # answer GET; try POST first, fall back to GET.
        try:
            return await self._request("POST", "/iserver/auth/status")
        except Exception:
            return await self._request("GET", "/iserver/auth/status")

    async def connect(self) -> None:
        """Validate the gateway session, re-auth if needed, and resolve the account."""
        status = await self._auth_status()
        authenticated = bool(status.get("authenticated"))

        if not authenticated:
            try:
                await self._request("POST", "/iserver/reauthenticate")
                await asyncio.sleep(1)
                status = await self._auth_status()
                authenticated = bool(status.get("authenticated"))
            except Exception as exc:
                logger.warning("Client Portal reauthenticate failed: %s", exc)

        if not authenticated:
            raise ConnectionError(
                "IBKR Client Portal session is not authenticated. Open "
                f"{self._base.replace('/v1/api', '')}/sso/Dispatcher in a browser, "
                "log in, then retry."
            )

        try:
            await self._request("POST", "/tickle")   # keepalive
        except Exception:
            pass

        await self._ensure_account()
        self._connected = True
        logger.info(
            "IBKR Client Portal connected — base=%s account=%s",
            self._base, self._account_id,
        )

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("IBKR Client Portal disconnected (local session flag cleared)")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def keepalive(self) -> bool:
        """Tickle the gateway session; return False if auth is lost."""
        if not self._connected:
            return False
        try:
            status = await self._auth_status()
            if not bool(status.get("authenticated")):
                self._connected = False
                return False
            await self._request("POST", "/tickle")
            return True
        except Exception as exc:
            logger.warning("Client Portal keepalive failed: %s", exc)
            self._connected = False
            return False

    async def _ensure_account(self) -> None:
        # /iserver/accounts must be called once to initialise the brokerage session.
        accounts = await self._request("GET", "/iserver/accounts")
        ids = accounts.get("accounts") if isinstance(accounts, dict) else None
        if self._account_id:
            return
        if not ids:
            raise ConnectionError("Client Portal returned no accounts")
        self._account_id = ids[0]

    @property
    def account_id(self) -> str:
        if not self._account_id:
            raise ConnectionError("Account id not resolved — call connect() first")
        return self._account_id

    # ── Contract resolution ─────────────────────────────────────────────────

    async def _resolve_conid(self, symbol: str, sec_type: str = "STK") -> int:
        key = f"{symbol}:{sec_type}"
        if key in self._conid_cache:
            return self._conid_cache[key]
        res = await self._request(
            "GET", "/iserver/secdef/search",
            params={"symbol": symbol, "secType": sec_type, "name": "false"},
        )
        rows = res if isinstance(res, list) else []
        if not rows:
            raise ValueError(f"No Client Portal conid found for {symbol} ({sec_type})")
        conid = int(rows[0]["conid"])
        self._conid_cache[key] = conid
        return conid

    async def _resolve_option_conid(self, leg: SpreadLeg) -> int:
        """Resolve a specific option leg's conid via secdef/info."""
        und_conid = await self._resolve_conid(leg.symbol, "STK")
        right = "C" if leg.option_type == "call" else "P"
        month = leg.expiration.strftime("%b%y").upper()  # e.g. JAN25
        info = await self._request(
            "GET", "/iserver/secdef/info",
            params={
                "conid": str(und_conid),
                "secType": "OPT",
                "month": month,
                "strike": float(leg.strike),
                "right": right,
            },
        )
        rows = info if isinstance(info, list) else [info]
        target_expiry = leg.expiration.strftime("%Y%m%d")
        for row in rows:
            mat = str(row.get("maturityDate", ""))
            if not mat or mat == target_expiry:
                return int(row["conid"])
        return int(rows[0]["conid"])

    # ── Market data ───────────────────────────────────────────────────────────

    async def _snapshot(self, conid: int, fields: list[str]) -> dict:
        """Fetch a market-data snapshot. The first call after subscribing can come
        back without the requested fields, so retry briefly."""
        params = {"conids": str(conid), "fields": ",".join(fields)}
        row: dict = {}
        for _ in range(3):
            data = await self._request("GET", "/iserver/marketdata/snapshot", params=params)
            row = (data[0] if isinstance(data, list) and data else {}) or {}
            if any(f in row for f in fields):
                break
            await asyncio.sleep(0.4)
        return row

    async def get_latest_quote(self, ticker: str) -> Quote:
        self._require_connection()
        conid = await self._resolve_conid(ticker)
        row = await self._snapshot(conid, [F_LAST, F_BID, F_ASK, F_BID_SIZE, F_ASK_SIZE])
        return Quote(
            symbol=ticker,
            bid_price=_dec(row.get(F_BID)),
            ask_price=_dec(row.get(F_ASK)),
            bid_size=int(_num(row.get(F_BID_SIZE))),
            ask_size=int(_num(row.get(F_ASK_SIZE))),
            timestamp=datetime.now(timezone.utc),
        )

    async def get_bars(
        self, ticker: str, timeframe: str = "1Day", limit: int = 100, end_date: str = ""
    ) -> list[Bar]:
        self._require_connection()
        conid = await self._resolve_conid(ticker)
        data = await self._request(
            "GET", "/iserver/marketdata/history",
            params={"conid": str(conid), "period": f"{limit}d",
                    "bar": "1d", "outsideRth": "false"},
        )
        rows = data.get("data", []) if isinstance(data, dict) else []
        result: list[Bar] = []
        for b in rows:
            ts_ms = b.get("t", 0)
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms else datetime.now(timezone.utc)
            result.append(Bar(
                timestamp=ts,
                open=_dec(b.get("o")), high=_dec(b.get("h")),
                low=_dec(b.get("l")), close=_dec(b.get("c")),
                volume=int(_num(b.get("v"))),
            ))
        return result

    async def get_options_chain(self, symbol: str, expiry: str) -> OptionsChain:
        """Best-effort chain via secdef/strikes + per-strike snapshots.

        This is heavier than the price routes (which use yfinance); failures are
        tolerated upstream. ``expiry`` is ``YYYY-MM-DD``.
        """
        self._require_connection()
        exp_date = date.fromisoformat(expiry)
        und_conid = await self._resolve_conid(symbol, "STK")
        month = exp_date.strftime("%b%y").upper()
        strikes_resp = await self._request(
            "GET", "/iserver/secdef/strikes",
            params={"conid": str(und_conid), "secType": "OPT", "month": month},
        )
        und_row = await self._snapshot(und_conid, [F_LAST])
        underlying_price = _dec(und_row.get(F_LAST))

        calls: list[OptionContract] = []
        puts: list[OptionContract] = []
        for right, bucket in (("call", calls), ("put", puts)):
            for strike in (strikes_resp.get("call" if right == "call" else "put", []) or []):
                leg = SpreadLeg(symbol=symbol, strike=Decimal(str(strike)),
                                expiration=exp_date, option_type=right,
                                action="BUY", quantity=1)
                try:
                    conid = await self._resolve_option_conid(leg)
                    snap = await self._snapshot(
                        conid, [F_BID, F_ASK, F_LAST, F_DELTA, F_GAMMA, F_THETA, F_VEGA, F_IV])
                except Exception:
                    continue
                bucket.append(OptionContract(
                    symbol=f"{symbol} {expiry} {strike}{right[0].upper()}",
                    underlying=symbol, expiration=exp_date,
                    strike=Decimal(str(strike)), option_type=right,
                    bid=_dec(snap.get(F_BID)), ask=_dec(snap.get(F_ASK)),
                    last=_dec(snap.get(F_LAST)), volume=0, open_interest=0,
                    greeks=Greeks(
                        delta=_num(snap.get(F_DELTA)), gamma=_num(snap.get(F_GAMMA)),
                        theta=_num(snap.get(F_THETA)), vega=_num(snap.get(F_VEGA)),
                        implied_vol=_num(snap.get(F_IV)),
                    ),
                ))
        return OptionsChain(
            underlying=symbol, expiration=exp_date,
            underlying_price=underlying_price, calls=calls, puts=puts,
            fetched_at=datetime.now(timezone.utc),
        )

    async def get_greeks(
        self, symbol: str, strike: float, expiry: str, option_type: str
    ) -> Greeks:
        self._require_connection()
        leg = SpreadLeg(symbol=symbol, strike=Decimal(str(strike)),
                        expiration=date.fromisoformat(expiry),
                        option_type="call" if option_type == "call" else "put",
                        action="BUY", quantity=1)
        conid = await self._resolve_option_conid(leg)
        snap = await self._snapshot(conid, [F_DELTA, F_GAMMA, F_THETA, F_VEGA, F_IV])
        return Greeks(
            delta=_num(snap.get(F_DELTA)), gamma=_num(snap.get(F_GAMMA)),
            theta=_num(snap.get(F_THETA)), vega=_num(snap.get(F_VEGA)),
            implied_vol=_num(snap.get(F_IV)),
        )

    # ── Account / positions ───────────────────────────────────────────────────

    async def get_account_summary(self) -> AccountSummary:
        self._require_connection()
        data = await self._request("GET", f"/portfolio/{self.account_id}/summary")
        return AccountSummary(
            account_id=self.account_id,
            net_liquidation=_amount(data.get("netliquidation")),
            cash_balance=_amount(data.get("totalcashvalue")),
            buying_power=_amount(data.get("buyingpower") or data.get("availablefunds")),
            trading_mode="paper" if settings.ibkr_trading_mode == "paper" else "live",
        )

    async def get_positions(self) -> list[Position]:
        self._require_connection()
        positions: list[Position] = []
        # Page through positions (100 per page) until an empty page.
        for page in range(0, 20):
            data = await self._request(
                "GET", f"/portfolio/{self.account_id}/positions/{page}")
            rows = data if isinstance(data, list) else []
            if not rows:
                break
            for p in rows:
                qty = int(_num(p.get("position")))
                if qty == 0:
                    continue
                asset = (p.get("assetClass") or "").upper()
                avg_cost = _dec(p.get("avgCost") or p.get("avgPrice"))
                if asset == "OPT":
                    expiry_raw = str(p.get("expiry") or "")
                    try:
                        exp = datetime.strptime(expiry_raw, "%Y%m%d").date()
                    except ValueError:
                        exp = date.today()
                    right = (p.get("putOrCall") or "C").upper()
                    positions.append(Position(
                        symbol=p.get("contractDesc") or str(p.get("conid", "")),
                        underlying=p.get("undSym") or p.get("ticker") or p.get("contractDesc", ""),
                        strike=_dec(p.get("strike")),
                        expiration=exp,
                        option_type="call" if right == "C" else "put",
                        quantity=qty, avg_cost=avg_cost,
                    ))
                else:
                    # Equity / ETF / fund — strike==0 sentinel (matches TWS client).
                    sym = p.get("ticker") or p.get("contractDesc") or str(p.get("conid", ""))
                    positions.append(Position(
                        symbol=sym, underlying=sym, strike=Decimal("0"),
                        expiration=date.today(), option_type="call",
                        quantity=qty, avg_cost=avg_cost,
                    ))
            if len(rows) < 100:
                break
        return positions

    # ── Order placement ───────────────────────────────────────────────────────

    async def _submit_orders(self, orders: list[dict]) -> dict:
        """POST one or more orders and walk the reply-confirmation handshake.

        The CP API answers an order with EITHER a status object (has ``order_id``)
        OR one/more "reply" objects (``id`` + ``message`` questions) that must be
        confirmed via ``/iserver/reply/{id}``. Returns the first resolved order
        object containing an ``order_id``/``orderId``.
        """
        resp = await self._request(
            "POST", f"/iserver/account/{self.account_id}/orders",
            json={"orders": orders},
        )
        items = resp if isinstance(resp, list) else [resp]

        for _ in range(10):  # bounded confirmation loop
            for item in items:
                if item.get("order_id") or item.get("orderId"):
                    return item
            # Need to confirm a warning/question reply.
            reply_ids = [it["id"] for it in items if it.get("id") and "message" in it]
            if not reply_ids:
                break
            confirmed: list[dict] = []
            for rid in reply_ids:
                r = await self._request(
                    "POST", f"/iserver/reply/{rid}", json={"confirmed": True})
                confirmed.extend(r if isinstance(r, list) else [r])
            items = confirmed

        # No resolved order id — surface whatever came back.
        return items[0] if items else {}

    async def _await_order(self, order_id: str, total_qty: int, timeout: int) -> tuple[str, int, float]:
        """Poll order status → (outcome, filled_qty, avg_price). Outcomes match the
        TWS client: filled / partial / cancelled / rejected / timeout."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            await asyncio.sleep(1)
            st = await self._request(
                "GET", f"/iserver/account/order/status/{order_id}")
            status = str(st.get("order_status") or st.get("status") or "")
            filled = int(_num(st.get("filled_quantity") or st.get("size_filled") or st.get("cumFill")))
            avg = _num(st.get("average_price") or st.get("avg_price") or st.get("avgPrice"))
            if status == "Filled" or (total_qty and filled >= total_qty):
                return "filled", filled, avg
            if status == "Rejected":
                return ("partial" if filled > 0 else "rejected"), filled, avg
            if status in _TERMINAL_CANCEL:
                return ("partial" if filled > 0 else "cancelled"), filled, avg
        # Best-effort final read for any partial fill at timeout.
        try:
            st = await self._request("GET", f"/iserver/account/order/status/{order_id}")
            filled = int(_num(st.get("filled_quantity") or st.get("size_filled") or 0))
            avg = _num(st.get("average_price") or st.get("avg_price"))
        except Exception:
            filled, avg = 0, 0.0
        return "timeout", filled, avg

    def _fill_timeout(self) -> int:
        return getattr(settings, "fill_timeout_seconds", 60)

    async def place_order(self, spread: SpreadOrder) -> OrderResult:
        """Submit an options order as a SINGLE order: a plain option for one leg,
        otherwise one combo (``conidex``). Honours MKT/LMT and reports partials."""
        self._require_connection()
        is_market = spread.order_type == "MKT"
        spread_qty, ratios = _combo_sizing(spread.legs)
        single = len(spread.legs) == 1
        tif = spread.time_in_force or "DAY"

        order: dict = {
            "acctId": self.account_id,
            "orderType": "MKT" if is_market else "LMT",
            "side": "BUY",
            "tif": tif,
            "quantity": spread_qty,
        }

        if single:
            leg = spread.legs[0]
            order["conid"] = await self._resolve_option_conid(leg)
            order["side"] = leg.action
            if not is_market:
                order["price"] = round(float(spread.limit_price), 2)
        else:
            # conidex: "<underlyingConid>;;;legConid/±ratio,...". A SELL leg gets a
            # negative ratio; the combo side is BUY.
            und_conid = await self._resolve_conid(spread.underlying, "STK")
            leg_parts = []
            for leg, ratio in zip(spread.legs, ratios):
                conid = await self._resolve_option_conid(leg)
                sign = "-" if leg.action == "SELL" else ""
                leg_parts.append(f"{conid}/{sign}{ratio}")
            order["conidex"] = f"{und_conid};;;" + ",".join(leg_parts)
            if not is_market:
                # Credit (limit_price > 0) → negative net combo price (we receive).
                order["price"] = round(-float(spread.limit_price), 2)

        logger.info(
            "CP submitting %s %s order: %s qty=%d%s",
            "single-leg" if single else "combo", order["orderType"],
            spread.underlying, spread_qty,
            "" if is_market else f" price={order.get('price')}",
        )

        resolved = await self._submit_orders([order])
        order_id = str(resolved.get("order_id") or resolved.get("orderId") or "")
        if not order_id:
            return OrderResult(
                order_id="unknown", status="rejected",
                filled_quantity=0, remaining_quantity=spread_qty,
                message=str(resolved.get("error") or resolved or "order not accepted"),
            )

        return self._equity_or_spread_result(
            await self._await_order(order_id, spread_qty, self._fill_timeout()),
            order_id, spread_qty, kind="spread",
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
        """Submit an equity order with real protective brackets.

        Child stop / take-profit orders reference the parent's ``cOID`` via
        ``parentId`` so IBKR transmits them as an OCA bracket — protective exits
        are actually placed, not silently dropped.
        """
        self._require_connection()
        conid = await self._resolve_conid(ticker, "STK")
        reverse = "SELL" if side == "BUY" else "BUY"
        parent_coid = f"olbos-{ticker}-{int(datetime.now().timestamp()*1000)}"

        type_map = {"market": "MKT", "limit": "LMT", "stop": "STP", "stop_limit": "STOP_LIMIT"}
        parent: dict = {
            "acctId": self.account_id, "conid": conid, "cOID": parent_coid,
            "orderType": type_map.get(order_type, "MKT"), "side": side,
            "tif": "DAY", "quantity": qty,
        }
        if limit_price is not None and order_type in ("limit", "stop_limit"):
            parent["price"] = float(limit_price)

        orders = [parent]
        if take_profit is not None:
            orders.append({
                "acctId": self.account_id, "conid": conid, "parentId": parent_coid,
                "orderType": "LMT", "side": reverse, "tif": "GTC",
                "quantity": qty, "price": float(take_profit),
            })
        if stop is not None:
            orders.append({
                "acctId": self.account_id, "conid": conid, "parentId": parent_coid,
                "orderType": "STP", "side": reverse, "tif": "GTC",
                "quantity": qty, "auxPrice": float(stop), "price": float(stop),
            })

        logger.info(
            "CP submitting equity %s order: %s %s x%d%s",
            order_type, side, ticker, qty,
            f"  [bracket stop={stop} tp={take_profit}]" if len(orders) > 1 else "",
        )

        resolved = await self._submit_orders(orders)
        order_id = str(resolved.get("order_id") or resolved.get("orderId") or "")
        if not order_id:
            return EquityOrderResult(
                order_id="unknown", status="rejected",
                filled_quantity=0, remaining_quantity=qty,
                message=str(resolved.get("error") or resolved or "order not accepted"),
            )

        return self._equity_or_spread_result(
            await self._await_order(order_id, qty, self._fill_timeout()),
            order_id, qty, kind="equity",
        )

    def _equity_or_spread_result(self, awaited, order_id, total_qty, kind):
        outcome, filled, avg = awaited
        Result = EquityOrderResult if kind == "equity" else OrderResult
        noun = "shares" if kind == "equity" else "contracts"
        if outcome == "filled":
            return Result(
                order_id=order_id, status="filled",
                fill_price=Decimal(str(round(avg, 4))),
                filled_at=datetime.now(timezone.utc),
                filled_quantity=filled, remaining_quantity=0,
                message=f"Filled {filled} {noun} @ ${avg:.4f}",
            )
        if outcome in ("cancelled", "rejected"):
            return Result(
                order_id=order_id, status=outcome,
                filled_quantity=0, remaining_quantity=total_qty, message=outcome,
            )
        if outcome == "partial" or (outcome == "timeout" and filled > 0):
            return Result(
                order_id=order_id, status="partial",
                fill_price=Decimal(str(round(avg, 4))),
                filled_at=datetime.now(timezone.utc),
                filled_quantity=filled, remaining_quantity=max(0, total_qty - filled),
                message=f"Partial fill {filled}/{total_qty} {noun} @ ${avg:.4f}",
            )
        return Result(
            order_id=order_id, status="submitted",
            filled_quantity=0, remaining_quantity=total_qty,
            message=f"Order working — no fill after {self._fill_timeout()}s",
        )

    # ── Order management (used by kill switch / manual cancels) ────────────────

    async def cancel_order(self, order_id: str) -> dict:
        self._require_connection()
        return await self._request(
            "DELETE", f"/iserver/account/{self.account_id}/order/{order_id}")

    async def cancel_all_orders(self) -> int:
        """Cancel every live order; returns the count cancelled."""
        self._require_connection()
        live = await self._request("GET", "/iserver/account/orders")
        orders = live.get("orders", []) if isinstance(live, dict) else []
        cancelled = 0
        for o in orders:
            status = str(o.get("status", "")).lower()
            if status in ("filled", "cancelled", "inactive"):
                continue
            oid = o.get("orderId") or o.get("order_id")
            if oid is None:
                continue
            try:
                await self.cancel_order(str(oid))
                cancelled += 1
            except Exception as exc:
                logger.warning("CP cancel order %s failed: %s", oid, exc)
        return cancelled
