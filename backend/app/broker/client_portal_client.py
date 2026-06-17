"""
IBKR Client Portal Web API broker client.

Talks to the clientportal.gw gateway (REST/WebSocket on :5000) instead of the
TWS socket protocol used by ib_insync. Selected via BROKER=ibkr_cp.

Scope (this pass): READ-ONLY + session keepalive.
  - connect()             — verify auth, init brokerage session, start /tickle
  - get_account_summary() — portfolio summary
  - get_positions()       — open option positions
  - get_latest_quote()    — equity bid/ask snapshot
  - get_bars()            — historical OHLCV
  - get_greeks()          — option greeks via snapshot
  - get_options_chain()   — best-effort chain via secdef + snapshot

Order execution (place_order / place_equity_order) is intentionally DISABLED
pending live verification against an authenticated gateway — it raises
NotImplementedError so nothing can mis-fire orders on a live account.

Auth note: the gateway requires a one-time browser login and times out daily;
this client keeps the session warm with /tickle but cannot auto-relogin.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

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
    SpreadOrder,
)
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Client Portal snapshot field IDs (see cpwebapi docs)
_F_LAST, _F_BID, _F_ASK, _F_BIDSZ, _F_ASKSZ = "31", "84", "86", "88", "85"
_F_IV, _F_DELTA, _F_GAMMA, _F_THETA, _F_VEGA = "7283", "7308", "7309", "7310", "7311"


class ClientPortalClient(BrokerInterface):
    """IBKR broker implementation over the Client Portal Web API."""

    supports_options: bool = True
    supports_equities: bool = True

    def __init__(self) -> None:
        base = settings.cp_gateway_url.rstrip("/")
        self.base_url = f"{base}/v1/api"
        self._client = httpx.AsyncClient(
            verify=settings.cp_gateway_verify_ssl, timeout=15.0
        )
        self._connected = False
        self._account_id: Optional[str] = settings.cp_account_id or None
        self._tickle_task: Optional[asyncio.Task] = None

    # ── HTTP helpers ──────────────────────────────────────────────────────────
    async def _get(self, path: str, params: dict | None = None) -> Any:
        r = await self._client.get(f"{self.base_url}{path}", params=params)
        r.raise_for_status()
        return r.json() if r.content else {}

    async def _post(self, path: str, json: dict | None = None) -> Any:
        r = await self._client.post(f"{self.base_url}{path}", json=json or {})
        r.raise_for_status()
        return r.json() if r.content else {}

    # ── Session lifecycle ─────────────────────────────────────────────────────
    async def connect(self) -> None:
        """Verify the gateway session is authenticated and start keepalive."""
        status = await self._auth_status()
        if not status.get("authenticated"):
            logger.warning(
                "Client Portal gateway NOT authenticated — open %s in a browser "
                "and log in. (status=%s)", settings.cp_gateway_url, status,
            )
            # Try a reauth in case the session merely lapsed
            try:
                await self._post("/iserver/reauthenticate")
            except Exception:
                pass

        # Initialise the brokerage session (required before market data / orders)
        try:
            await self._get("/iserver/accounts")
        except Exception as exc:
            logger.debug("iserver/accounts init failed: %s", exc)

        await self._resolve_account_id()
        self._connected = bool(status.get("authenticated"))
        if self._tickle_task is None:
            self._tickle_task = asyncio.create_task(self._keepalive())
        logger.info(
            "Client Portal connected=%s account=%s url=%s",
            self._connected, self._account_id, settings.cp_gateway_url,
        )

    async def disconnect(self) -> None:
        if self._tickle_task:
            self._tickle_task.cancel()
            self._tickle_task = None
        await self._client.aclose()
        self._connected = False

    def isConnected(self) -> bool:  # noqa: N802 — mirror ib_insync API used by main.py
        return self._connected

    async def _keepalive(self) -> None:
        """Ping /tickle so the brokerage session does not idle out."""
        while True:
            try:
                await asyncio.sleep(settings.cp_tickle_interval_s)
                res = await self._get("/tickle")
                self._connected = bool(
                    res.get("iserver", {}).get("authStatus", {}).get("authenticated", False)
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Client Portal tickle failed: %s", exc)
                self._connected = False

    async def _auth_status(self) -> dict:
        try:
            return await self._post("/iserver/auth/status")
        except Exception as exc:
            logger.debug("auth/status failed: %s", exc)
            return {}

    async def _resolve_account_id(self) -> Optional[str]:
        if self._account_id:
            return self._account_id
        try:
            accts = await self._get("/portfolio/accounts")
            if isinstance(accts, list) and accts:
                self._account_id = accts[0].get("accountId") or accts[0].get("id")
        except Exception as exc:
            logger.debug("resolve account id failed: %s", exc)
        return self._account_id

    def _require_connection(self) -> None:
        if not self._connected:
            raise ConnectionError(
                "Client Portal gateway session is not authenticated. "
                f"Open {settings.cp_gateway_url} in a browser and log in."
            )

    # ── Contract resolution ───────────────────────────────────────────────────
    async def _resolve_stock_conid(self, ticker: str) -> Optional[int]:
        try:
            res = await self._get("/iserver/secdef/search", {"symbol": ticker})
            if isinstance(res, list) and res:
                return int(res[0]["conid"])
        except Exception as exc:
            logger.debug("conid resolve failed for %s: %s", ticker, exc)
        return None

    async def _snapshot(self, conids: list[int], fields: list[str]) -> dict[int, dict]:
        """Snapshot quote/greeks. CP often needs two calls before data is warm."""
        params = {"conids": ",".join(str(c) for c in conids), "fields": ",".join(fields)}
        out: dict[int, dict] = {}
        for _ in range(2):
            data = await self._get("/iserver/marketdata/snapshot", params)
            if isinstance(data, list):
                for row in data:
                    cid = row.get("conid")
                    if cid is not None:
                        out[int(cid)] = row
            if all(f in out.get(conids[0], {}) for f in fields[:1]):
                break
            await asyncio.sleep(0.4)
        return out

    # ── Reads ─────────────────────────────────────────────────────────────────
    async def get_account_summary(self) -> AccountSummary:
        self._require_connection()
        acct = await self._resolve_account_id() or "unknown"
        summary = await self._get(f"/portfolio/{acct}/summary")

        def _amt(key: str) -> Decimal:
            node = summary.get(key, {}) if isinstance(summary, dict) else {}
            return Decimal(str(node.get("amount", 0) if isinstance(node, dict) else node or 0))

        return AccountSummary(
            account_id=acct,
            net_liquidation=_amt("netliquidation"),
            cash_balance=_amt("totalcashvalue"),
            buying_power=_amt("buyingpower"),
            trading_mode="paper" if str(acct).upper().startswith("D") else "live",
        )

    async def get_positions(self) -> list[Position]:
        self._require_connection()
        acct = await self._resolve_account_id() or "unknown"
        positions: list[Position] = []
        page = 0
        while True:
            rows = await self._get(f"/portfolio/{acct}/positions/{page}")
            if not isinstance(rows, list) or not rows:
                break
            for r in rows:
                if (r.get("assetClass") or "").upper() != "OPT":
                    continue
                try:
                    positions.append(Position(
                        symbol=r.get("contractDesc", r.get("ticker", "")),
                        underlying=r.get("undSym", r.get("ticker", "")),
                        strike=Decimal(str(r.get("strike", 0) or 0)),
                        expiration=self._parse_expiry(r.get("expiry")),
                        option_type="call" if str(r.get("putOrCall", "C")).upper().startswith("C") else "put",
                        quantity=int(r.get("position", 0) or 0),
                        avg_cost=Decimal(str(r.get("avgCost", 0) or 0)),
                        current_price=Decimal(str(r["mktPrice"])) if r.get("mktPrice") is not None else None,
                        unrealized_pnl=Decimal(str(r["unrealizedPnl"])) if r.get("unrealizedPnl") is not None else None,
                    ))
                except Exception as exc:
                    logger.debug("position parse skipped: %s", exc)
            if len(rows) < 30:  # CP pages are 30 rows
                break
            page += 1
        return positions

    async def get_latest_quote(self, ticker: str) -> Quote:
        self._require_connection()
        conid = await self._resolve_stock_conid(ticker)
        if conid is None:
            raise ValueError(f"Could not resolve conid for {ticker}")
        snap = await self._snapshot([conid], [_F_BID, _F_ASK, _F_BIDSZ, _F_ASKSZ])
        row = snap.get(conid, {})

        def _d(v) -> Decimal:
            try:
                return Decimal(str(v))
            except Exception:
                return Decimal("0")

        return Quote(
            symbol=ticker,
            bid_price=_d(row.get(_F_BID, 0)),
            ask_price=_d(row.get(_F_ASK, 0)),
            bid_size=int(float(row.get(_F_BIDSZ, 0) or 0)),
            ask_size=int(float(row.get(_F_ASKSZ, 0) or 0)),
            timestamp=datetime.now(timezone.utc),
        )

    async def get_bars(
        self, ticker: str, timeframe: str = "1Day", limit: int = 100
    ) -> list[Bar]:
        self._require_connection()
        conid = await self._resolve_stock_conid(ticker)
        if conid is None:
            raise ValueError(f"Could not resolve conid for {ticker}")
        bar = {"1Day": "1d", "1Hour": "1h", "1Min": "1min"}.get(timeframe, "1d")
        period = f"{max(limit, 1)}d" if bar == "1d" else f"{max(limit, 1)}h"
        data = await self._get("/iserver/marketdata/history", {
            "conid": conid, "period": period, "bar": bar, "outsideRth": "false",
        })
        bars: list[Bar] = []
        for p in (data.get("data", []) if isinstance(data, dict) else []):
            try:
                bars.append(Bar(
                    timestamp=datetime.fromtimestamp(p["t"] / 1000, tz=timezone.utc),
                    open=Decimal(str(p["o"])), high=Decimal(str(p["h"])),
                    low=Decimal(str(p["l"])), close=Decimal(str(p["c"])),
                    volume=int(p.get("v", 0) or 0),
                ))
            except Exception:
                continue
        return bars[-limit:]

    async def get_greeks(
        self, symbol: str, strike: float, expiry: str, option_type: str
    ) -> Greeks:
        self._require_connection()
        conid = await self._resolve_option_conid(symbol, strike, expiry, option_type)
        if conid is None:
            raise ValueError(f"Could not resolve option conid for {symbol} {strike} {expiry}")
        snap = await self._snapshot(
            [conid], [_F_DELTA, _F_GAMMA, _F_THETA, _F_VEGA, _F_IV]
        )
        row = snap.get(conid, {})

        def _f(v) -> float:
            try:
                return float(str(v).replace("%", ""))
            except Exception:
                return 0.0

        iv = _f(row.get(_F_IV, 0))
        return Greeks(
            delta=_f(row.get(_F_DELTA, 0)), gamma=_f(row.get(_F_GAMMA, 0)),
            theta=_f(row.get(_F_THETA, 0)), vega=_f(row.get(_F_VEGA, 0)),
            implied_vol=iv / 100 if iv > 1.5 else iv,
        )

    async def get_options_chain(self, symbol: str, expiry: str) -> OptionsChain:
        """
        Best-effort chain via secdef strikes + snapshots. This is expensive over
        the Web API; OlbosQuant primarily sources chains from yfinance, so this
        is provided for completeness. Returns ATM-window strikes only.
        """
        self._require_connection()
        und_conid = await self._resolve_stock_conid(symbol)
        if und_conid is None:
            raise ValueError(f"Could not resolve underlying conid for {symbol}")
        exp_dt = date.fromisoformat(expiry)
        month = exp_dt.strftime("%b%y").upper()
        spot_q = await self.get_latest_quote(symbol)
        spot = float((spot_q.bid_price + spot_q.ask_price) / 2) or 0.0

        try:
            strikes_res = await self._get("/iserver/secdef/strikes", {
                "conid": und_conid, "sectype": "OPT", "month": month,
            })
            all_strikes = sorted(set(strikes_res.get("call", [])) | set(strikes_res.get("put", [])))
        except Exception as exc:
            raise ValueError(f"strikes lookup failed for {symbol}: {exc}")

        window = sorted(all_strikes, key=lambda s: abs(s - spot))[:10] if spot else all_strikes[:10]
        calls, puts = [], []
        for k in sorted(window):
            for right, bucket in (("call", calls), ("put", puts)):
                try:
                    g = await self.get_greeks(symbol, k, expiry, right)
                    bucket.append(OptionContract(
                        symbol=f"{symbol} {expiry} {k}{right[0].upper()}",
                        underlying=symbol, expiration=exp_dt, strike=Decimal(str(k)),
                        option_type=right, bid=Decimal("0"), ask=Decimal("0"),
                        last=Decimal("0"), volume=0, open_interest=0, greeks=g,
                    ))
                except Exception:
                    continue

        return OptionsChain(
            underlying=symbol, expiration=exp_dt,
            underlying_price=Decimal(str(spot)), calls=calls, puts=puts,
            fetched_at=datetime.now(timezone.utc),
        )

    async def _resolve_option_conid(
        self, symbol: str, strike: float, expiry: str, option_type: str
    ) -> Optional[int]:
        try:
            und_conid = await self._resolve_stock_conid(symbol)
            if und_conid is None:
                return None
            exp_dt = date.fromisoformat(expiry)
            month = exp_dt.strftime("%b%y").upper()
            right = "C" if option_type.lower().startswith("c") else "P"
            info = await self._get("/iserver/secdef/info", {
                "conid": und_conid, "sectype": "OPT", "month": month,
                "strike": strike, "right": right,
            })
            rows = info if isinstance(info, list) else [info]
            for row in rows:
                mat = row.get("maturityDate")  # YYYYMMDD
                if mat and mat == exp_dt.strftime("%Y%m%d"):
                    return int(row["conid"])
            if rows and rows[0].get("conid"):
                return int(rows[0]["conid"])
        except Exception as exc:
            logger.debug("option conid resolve failed: %s", exc)
        return None

    @staticmethod
    def _parse_expiry(raw) -> date:
        if not raw:
            return date.today()
        s = str(raw)
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return date.today()

    # ── Orders — DISABLED pending live verification ──────────────────────────
    async def place_order(self, spread: SpreadOrder) -> OrderResult:
        raise NotImplementedError(
            "Client Portal order execution is not enabled yet. Reads/keepalive "
            "only in this build — verify the authenticated gateway, then the "
            "order + reply-confirmation flow can be implemented. Use BROKER=ibkr "
            "(ib_insync) for live execution in the meantime."
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
        raise NotImplementedError(
            "Client Portal equity order execution is not enabled yet (reads-only "
            "build). Use BROKER=ibkr (ib_insync) for live execution."
        )
