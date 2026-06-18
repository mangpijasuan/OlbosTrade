"""
IBKR Options Flow Ingest Service.

Streams real-time options prints from the *existing* IBKR connection, classifies
each one (trade type, sentiment, sweep), persists it to the ``options_flow``
table, and publishes it to the ``options_flow_live`` pub/sub channel for
WebSocket fanout to the frontend.

IMPORTANT — data subscription reality
-------------------------------------
``reqTickByTickData(contract, 'AllLast')`` requires a LIVE real-time market-data
subscription (OPRA for US options). OlbosQuant currently runs IBKR on
delayed-frozen data (``reqMarketDataType(4)``) and uses yfinance for all market
data, so this service is GATED behind ``settings.options_flow_enabled`` (default
False). When the flag is off it stays idle — no second IBKR connection, no
errors. Set the flag (and have a live OPRA subscription) to stream for real.

``settings.options_flow_demo_mode`` emits synthetic ticks so the full pipeline
(ingest → sweep → DB → WS → UI) can be exercised end-to-end without live data.

Broker selection picks the live source automatically:
  - BROKER=ibkr     → ib_insync reqTickByTickData('AllLast') (full per-print
                      feed with exchange attribution → real sweep detection)
  - BROKER=ibkr_cp  → Client Portal Web API market-data WebSocket
                      (snapshot/field-update fidelity — see _run_live_cp caveats:
                      no exchange attribution, sweep detection disabled)

Reuse contract (per spec):
  - Reuses the existing broker's ``ib`` handle (no second IBKR connection).
  - Reuses Redis via app.core.redis (in-process fallback when unavailable).
  - Reuses the async DB session from app.core.database.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis import publish_json
from app.models.options_flow import OptionsFlow
from app.services.sweep_detector import SweepDetector
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Value object ────────────────────────────────────────────────────────────
@dataclass
class FlowTick:
    """A single classified options print, ready to persist / publish."""

    ticker: str
    strike: float
    expiry: str          # ISO date
    right: str           # 'C' | 'P'
    exchange: str
    timestamp: str       # ISO datetime (UTC)
    premium: float
    size: int
    trade_type: str      # 'sweep' | 'block' | 'single'
    sentiment: str       # 'bullish' | 'bearish' | 'neutral'
    iv: Optional[float]
    delta: Optional[float]
    dte: int
    relative_volume: float
    sweep_confirmed: bool = False
    large_sweep: bool = False


# ── Pure classification helpers (unit-testable, no I/O) ─────────────────────
def classify_sentiment(
    right: str, price: float, bid: Optional[float], ask: Optional[float]
) -> str:
    """
    bullish  = call at ask OR put at bid
    bearish  = put at ask  OR call at bid
    neutral  = mid / undetermined
    """
    if bid is None or ask is None or ask <= 0:
        return "neutral"
    tol = max((ask - bid) * 0.25, 0.01)  # quarter-spread tolerance
    at_ask = price >= ask - tol
    at_bid = price <= bid + tol
    r = right.upper()
    if r == "C":
        if at_ask:
            return "bullish"
        if at_bid:
            return "bearish"
    elif r == "P":
        if at_ask:
            return "bearish"
        if at_bid:
            return "bullish"
    return "neutral"


def classify_trade_type(size: int, sweep_confirmed: bool, block_min_size: int) -> str:
    """sweep (multi-venue burst) > block (single venue, large) > single."""
    if sweep_confirmed:
        return "sweep"
    if size > block_min_size:
        return "block"
    return "single"


def compute_dte(expiry: date, today: Optional[date] = None) -> int:
    today = today or date.today()
    return max((expiry - today).days, 0)


# ── Service ─────────────────────────────────────────────────────────────────
class OptionsFlowIngestService:
    """Owns the ingest lifecycle. Instantiated once and driven from lifespan."""

    def __init__(self) -> None:
        self._sweep = SweepDetector()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._active_subs: list = []  # IBKR contracts we subscribed to
        # latest bid/ask per contract conId for sentiment classification
        self._quotes: dict[int, tuple[float, float]] = {}

    # ── lifecycle ───────────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._running:
            return
        if not settings.options_flow_enabled and not settings.options_flow_demo_mode:
            logger.info(
                "Options flow ingest idle — options_flow_enabled=False "
                "(set it once a live OPRA subscription is available)"
            )
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Options flow ingest starting — demo=%s live=%s watchlist=%s",
            settings.options_flow_demo_mode,
            settings.options_flow_enabled,
            settings.get_options_flow_watchlist(),
        )

    async def stop(self) -> None:
        self._running = False
        await self._unsubscribe_all()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("Options flow ingest stopped")

    async def _run(self) -> None:
        try:
            if settings.options_flow_demo_mode:
                await self._run_demo()
            elif settings.broker.lower().strip() == "ibkr_cp":
                await self._run_live_cp()
            else:
                await self._run_live()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Options flow ingest crashed: %s", exc, exc_info=True)

    # ── live IBKR path ────────────────────────────────────────────────────────
    async def _run_live(self) -> None:
        """Subscribe to tick-by-tick AllLast on the existing IBKR connection."""
        ib = self._get_ib()
        if ib is None:
            logger.warning(
                "Options flow: no IBKR connection available — staying idle"
            )
            return

        try:
            from ib_insync import Option, Stock
        except Exception as exc:
            logger.warning("Options flow: ib_insync unavailable (%s)", exc)
            return

        contracts = await self._select_contracts(ib, Stock, Option)
        if not contracts:
            logger.warning("Options flow: no contracts resolved to subscribe to")
            return

        for c in contracts[: settings.options_flow_max_contracts]:
            try:
                # A quote line for bid/ask (for sentiment) + tick-by-tick trades.
                ticker = ib.reqMktData(c, "", False, False)
                ticker.updateEvent += self._on_quote_update
                tbt = ib.reqTickByTickData(c, "AllLast", 0, False)
                tbt.updateEvent += self._on_tick
                self._active_subs.append(c)
            except Exception as exc:
                logger.warning("Subscribe failed for %s: %s", c.localSymbol, exc)

        logger.info(
            "Options flow: subscribed to %d contracts (cap %d)",
            len(self._active_subs), settings.options_flow_max_contracts,
        )

        # Keep the task alive; ib_insync delivers ticks via the event loop.
        while self._running:
            self._sweep.prune()
            await asyncio.sleep(30)

    def _get_ib(self):
        """Return the existing IBKR `ib` handle, or None. No new connection."""
        try:
            from app.broker.broker_factory import get_broker
            broker = get_broker()
            ib = getattr(broker, "ib", None)
            if ib is not None and ib.isConnected():
                return ib
        except Exception as exc:
            logger.debug("Options flow: broker/ib lookup failed: %s", exc)
        return None

    async def _select_contracts(self, ib, Stock, Option) -> list:
        """Resolve a bounded set of near-ATM option contracts within max DTE."""
        contracts: list = []
        max_dte = settings.options_flow_max_dte
        today = date.today()
        per_ticker = max(1, settings.options_flow_max_contracts //
                         max(len(settings.get_options_flow_watchlist()), 1))

        for symbol in settings.get_options_flow_watchlist():
            try:
                stock = Stock(symbol, "SMART", "USD")
                await ib.qualifyContractsAsync(stock)
                [ticker] = await ib.reqTickersAsync(stock)
                spot = ticker.marketPrice() or ticker.close
                if not spot or spot != spot:  # NaN guard
                    continue

                chains = await ib.reqSecDefOptParamsAsync(
                    stock.symbol, "", stock.secType, stock.conId
                )
                chain = next((c for c in chains if c.exchange == "SMART"), None)
                if chain is None:
                    continue

                expiries = sorted(
                    e for e in chain.expirations
                    if 0 <= (datetime.strptime(e, "%Y%m%d").date() - today).days <= max_dte
                )[:2]
                # ~ATM strikes only — keep market-data lines bounded
                strikes = sorted(chain.strikes, key=lambda s: abs(s - spot))[:4]

                made = 0
                for expiry in expiries:
                    for strike in strikes:
                        for right in ("C", "P"):
                            if made >= per_ticker:
                                break
                            opt = Option(symbol, expiry, strike, right, "SMART")
                            contracts.append(opt)
                            made += 1
                if made:
                    await ib.qualifyContractsAsync(*contracts[-made:])
            except Exception as exc:
                logger.warning("Contract selection failed for %s: %s", symbol, exc)
        return contracts

    def _on_quote_update(self, ticker) -> None:
        try:
            conId = ticker.contract.conId
            bid = ticker.bid if ticker.bid and ticker.bid > 0 else None
            ask = ticker.ask if ticker.ask and ticker.ask > 0 else None
            if bid is not None and ask is not None:
                self._quotes[conId] = (bid, ask)
        except Exception:
            pass

    def _on_tick(self, ticker) -> None:
        """ib_insync tick-by-tick callback — schedule async processing."""
        try:
            last = ticker.tickByTicks[-1] if ticker.tickByTicks else None
            if last is None:
                return
            c = ticker.contract
            bid, ask = self._quotes.get(c.conId, (None, None))
            greeks = getattr(ticker, "modelGreeks", None)
            asyncio.create_task(self._handle_print(
                symbol=c.symbol,
                strike=float(c.strike),
                expiry=datetime.strptime(c.lastTradeDateOrContractMonth, "%Y%m%d").date(),
                right="C" if c.right.upper().startswith("C") else "P",
                exchange=getattr(last, "exchange", "") or "",
                price=float(last.price),
                size=int(last.size),
                bid=bid,
                ask=ask,
                iv=float(greeks.impliedVol) if greeks and greeks.impliedVol else None,
                delta=float(greeks.delta) if greeks and greeks.delta else None,
            ))
        except Exception as exc:
            logger.debug("Options flow tick parse error: %s", exc)

    # ── live Client Portal (CP Web API WebSocket) path ───────────────────────
    # FIDELITY CAVEAT: the CP market-data WebSocket streams per-contract FIELD
    # updates (last price / size / bid / ask / greeks), NOT a true per-print
    # time-and-sales feed with exchange attribution. Consequently:
    #   - exchange is unknown (tagged "CP")
    #   - multi-venue SWEEP detection is effectively disabled (single venue →
    #     distinct_exchanges is always 1, so sweeps never confirm — by design,
    #     to avoid false positives). trade_type is size-based (block/single).
    #   - size is approximate (last-size field may lag the last-price update).
    # Still requires a LIVE OPRA subscription on the IBKR account.
    def _cp_ws_url(self) -> str:
        base = settings.cp_gateway_url.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        return f"{base}/v1/api/ws"

    @staticmethod
    def _cp_num(v) -> Optional[float]:
        """Parse a CP field value (may be '$5.20', '1,234', '12.3%', or number)."""
        if v is None:
            return None
        try:
            s = str(v).replace("$", "").replace(",", "").replace("%", "").strip()
            return float(s) if s not in ("", "-") else None
        except Exception:
            return None

    async def _run_live_cp(self) -> None:
        from app.broker.broker_factory import get_broker

        broker = get_broker()
        if not hasattr(broker, "_get"):
            logger.warning("Options flow (CP): active broker is not Client Portal — idle")
            return
        # Ensure the gateway session is authenticated (no second connection).
        if hasattr(broker, "connect") and not broker.isConnected():
            try:
                await broker.connect()
            except Exception as exc:
                logger.warning("Options flow (CP): connect failed: %s", exc)
        if not broker.isConnected():
            logger.warning(
                "Options flow (CP): gateway not authenticated — open %s in a "
                "browser and log in. Staying idle.", settings.cp_gateway_url,
            )
            return

        contracts = await self._select_cp_contracts(broker)
        if not contracts:
            logger.warning("Options flow (CP): no contracts resolved — idle")
            return

        try:
            import json as _json
            import ssl as _ssl
            import websockets
        except Exception as exc:
            logger.warning("Options flow (CP): websockets unavailable (%s)", exc)
            return

        ssl_ctx = None
        if self._cp_ws_url().startswith("wss://") and not settings.cp_gateway_verify_ssl:
            ssl_ctx = _ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = _ssl.CERT_NONE

        meta = {c["conid"]: c for c in contracts[: settings.options_flow_max_contracts]}
        quotes: dict[int, tuple[float, float]] = {}
        last_size: dict[int, int] = {}

        # Session id for the WS handshake (from the authenticated gateway).
        try:
            session_id = (await broker._get("/tickle")).get("session")
        except Exception:
            session_id = None

        fields = ["31", "84", "86", "7059", "7283", "7308"]  # last,bid,ask,size,iv,delta
        url = self._cp_ws_url()
        logger.info(
            "Options flow (CP): connecting WS %s for %d contracts "
            "(snapshot-fidelity — sweep detection disabled)", url, len(meta),
        )
        async with websockets.connect(url, ssl=ssl_ctx, max_size=None) as ws:
            if session_id:
                await ws.send(_json.dumps({"session": session_id}))
            for conid in meta:
                await ws.send('smd+%d+{"fields":%s}' % (conid, _json.dumps(fields)))

            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = _json.loads(raw)
                except Exception:
                    continue
                topic = msg.get("topic", "")
                if not topic.startswith("smd+"):
                    continue  # heartbeats / system / auth-status messages
                try:
                    conid = int(msg.get("conid") or topic.split("+")[1])
                except Exception:
                    continue
                m = meta.get(conid)
                if m is None:
                    continue

                bid = self._cp_num(msg.get("84"))
                ask = self._cp_num(msg.get("86"))
                if bid is not None and ask is not None:
                    quotes[conid] = (bid, ask)
                else:
                    bid, ask = quotes.get(conid, (None, None))

                if "7059" in msg:
                    sz = self._cp_num(msg.get("7059"))
                    if sz:
                        last_size[conid] = int(sz)

                # Only emit on a last-price (trade) update.
                if "31" not in msg:
                    continue
                price = self._cp_num(msg.get("31"))
                size = last_size.get(conid, 0)
                if not price or size <= 0:
                    continue

                iv = self._cp_num(msg.get("7283"))
                if iv is not None and iv > 1.5:
                    iv = iv / 100  # CP returns IV as a percentage
                delta = self._cp_num(msg.get("7308"))

                await self._handle_print(
                    symbol=m["symbol"], strike=m["strike"], expiry=m["expiry"],
                    right=m["right"], exchange="CP", price=price, size=size,
                    bid=bid, ask=ask, iv=iv, delta=delta,
                )

    async def _select_cp_contracts(self, broker) -> list[dict]:
        """Resolve near-ATM option conids within max DTE via the CP secdef API."""
        contracts: list[dict] = []
        today = date.today()
        max_dte = settings.options_flow_max_dte
        watchlist = settings.get_options_flow_watchlist()
        per_ticker = max(1, settings.options_flow_max_contracts // max(len(watchlist), 1))

        for symbol in watchlist:
            try:
                und = await broker._resolve_stock_conid(symbol)
                if not und:
                    continue
                q = await broker.get_latest_quote(symbol)
                spot = float((q.bid_price + q.ask_price) / 2) or 0.0
                made = 0
                for m_off in range(3):  # this month + next two
                    yr, mo = today.year, today.month + m_off
                    yr += (mo - 1) // 12
                    mo = ((mo - 1) % 12) + 1
                    month = date(yr, mo, 1).strftime("%b%y").upper()
                    try:
                        strikes_res = await broker._get(
                            "/iserver/secdef/strikes",
                            {"conid": und, "sectype": "OPT", "month": month},
                        )
                    except Exception:
                        continue
                    all_strikes = sorted(
                        set(strikes_res.get("call", [])) | set(strikes_res.get("put", []))
                    )
                    if not all_strikes:
                        continue
                    near = (sorted(all_strikes, key=lambda s: abs(s - spot))[:3]
                            if spot else all_strikes[:3])
                    for strike in near:
                        for right in ("C", "P"):
                            if made >= per_ticker:
                                break
                            try:
                                info = await broker._get(
                                    "/iserver/secdef/info",
                                    {"conid": und, "sectype": "OPT", "month": month,
                                     "strike": strike, "right": right},
                                )
                            except Exception:
                                continue
                            rows = info if isinstance(info, list) else [info]
                            for row in rows:
                                mat, cid = row.get("maturityDate"), row.get("conid")
                                if not (mat and cid):
                                    continue
                                try:
                                    exp = datetime.strptime(str(mat), "%Y%m%d").date()
                                except ValueError:
                                    continue
                                if not (0 <= (exp - today).days <= max_dte):
                                    continue
                                contracts.append({
                                    "conid": int(cid), "symbol": symbol,
                                    "strike": float(strike), "expiry": exp, "right": right,
                                })
                                made += 1
                                break
            except Exception as exc:
                logger.warning("Options flow (CP): contract select failed for %s: %s", symbol, exc)
        return contracts[: settings.options_flow_max_contracts]

    # ── demo path ─────────────────────────────────────────────────────────────
    async def _run_demo(self) -> None:
        """Emit synthetic ticks to exercise the full pipeline without live data."""
        watchlist = settings.get_options_flow_watchlist()
        spots = {"SPY": 540, "QQQ": 470, "IWM": 205, "AAPL": 210,
                 "TSLA": 250, "NVDA": 120}
        exchanges = ["CBOE", "ISE", "PHLX", "AMEX", "BOX", "MIAX"]
        while self._running:
            try:
                symbol = random.choice(watchlist)
                spot = spots.get(symbol, 100)
                strike = round(spot + random.choice([-10, -5, 0, 5, 10]))
                right = random.choice(["C", "P"])
                expiry = date.today() + timedelta(days=random.choice([7, 14, 30, 45]))
                price = round(random.uniform(0.5, 8.0), 2)
                spread = round(price * 0.04, 2)
                bid, ask = price - spread, price + spread
                # bias trades toward bid/ask so sentiment isn't all-neutral
                fill = random.choice([bid, ask, (bid + ask) / 2])
                size = random.choice([1, 5, 25, 100, 300, 600, 1200])
                iv = round(random.uniform(0.12, 0.65), 4)
                delta = round(random.uniform(0.05, 0.65) * (1 if right == "C" else -1), 4)

                # occasionally simulate a multi-venue sweep burst
                burst = [random.choice(exchanges) for _ in range(
                    random.choice([1, 1, 1, 3, 4]))]
                for ex in burst:
                    await self._handle_print(
                        symbol=symbol, strike=float(strike), expiry=expiry,
                        right=right, exchange=ex, price=round(fill, 2),
                        size=size, bid=bid, ask=ask, iv=iv, delta=delta,
                    )
            except Exception as exc:
                logger.debug("Demo tick error: %s", exc)
            await asyncio.sleep(random.uniform(0.3, 1.2))

    # ── shared processing ─────────────────────────────────────────────────────
    async def _handle_print(
        self,
        symbol: str,
        strike: float,
        expiry: date,
        right: str,
        exchange: str,
        price: float,
        size: int,
        bid: Optional[float],
        ask: Optional[float],
        iv: Optional[float] = None,
        delta: Optional[float] = None,
    ) -> None:
        try:
            if price <= 0 or size <= 0:
                return
            premium = round(price * size * 100, 2)
            expiry_iso = expiry.isoformat()

            sweep = self._sweep.record(
                ticker=symbol, strike=strike, expiry_iso=expiry_iso,
                right=right, exchange=exchange, premium=premium,
            )
            trade_type = classify_trade_type(
                size, sweep.sweep_confirmed, settings.options_flow_block_min_size
            )
            sentiment = classify_sentiment(right, price, bid, ask)
            rel_vol = await self._relative_volume(symbol, strike, expiry, right, size)

            tick = FlowTick(
                ticker=symbol,
                strike=strike,
                expiry=expiry_iso,
                right=right,
                exchange=(exchange or "").upper(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                premium=premium,
                size=size,
                trade_type=trade_type,
                sentiment=sentiment,
                iv=iv,
                delta=delta,
                dte=compute_dte(expiry),
                relative_volume=rel_vol,
                sweep_confirmed=sweep.sweep_confirmed,
                large_sweep=sweep.large_sweep,
            )

            await self._persist(tick)
            await publish_json(settings.options_flow_channel, asdict(tick))
        except Exception as exc:
            logger.warning("Options flow _handle_print failed: %s", exc)

    async def _relative_volume(
        self, symbol: str, strike: float, expiry: date, right: str, size: int
    ) -> float:
        """size / avg size over last 30 days for this contract. 1.0 if no history."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            async with AsyncSessionLocal() as session:
                avg = (await session.execute(
                    select(func.avg(OptionsFlow.size)).where(
                        OptionsFlow.ticker == symbol,
                        OptionsFlow.strike == Decimal(str(strike)),
                        OptionsFlow.expiry == expiry,
                        OptionsFlow.right == right,
                        OptionsFlow.timestamp >= cutoff,
                    )
                )).scalar()
            if avg and float(avg) > 0:
                return round(size / float(avg), 2)
        except Exception as exc:
            logger.debug("relative_volume query failed: %s", exc)
        return 1.0

    async def _persist(self, tick: FlowTick) -> None:
        try:
            async with AsyncSessionLocal() as session:
                session.add(OptionsFlow(
                    ticker=tick.ticker,
                    strike=Decimal(str(tick.strike)),
                    expiry=date.fromisoformat(tick.expiry),
                    right=tick.right,
                    exchange=tick.exchange,
                    timestamp=datetime.fromisoformat(tick.timestamp),
                    premium=Decimal(str(tick.premium)),
                    size=tick.size,
                    trade_type=tick.trade_type,
                    sentiment=tick.sentiment,
                    iv=Decimal(str(tick.iv)) if tick.iv is not None else None,
                    delta=Decimal(str(tick.delta)) if tick.delta is not None else None,
                    dte=tick.dte,
                    relative_volume=Decimal(str(tick.relative_volume)),
                    sweep_confirmed=tick.sweep_confirmed,
                    large_sweep=tick.large_sweep,
                ))
                await session.commit()
        except Exception as exc:
            logger.warning("Options flow persist failed: %s", exc)

    async def _unsubscribe_all(self) -> None:
        ib = self._get_ib()
        if ib is not None:
            for c in self._active_subs:
                try:
                    ib.cancelTickByTickData(c, "AllLast")
                    ib.cancelMktData(c)
                except Exception:
                    pass
        self._active_subs.clear()
        self._quotes.clear()


# ── Data retention / archival (nightly APScheduler job) ─────────────────────
async def archive_old_flow() -> int:
    """
    Archive options_flow rows older than the retention window to a JSONL file
    under ``options_flow_archive_dir`` and delete them. Returns rows archived.
    """
    import json
    import os

    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.options_flow_retention_days
    )
    archived = 0
    try:
        os.makedirs(settings.options_flow_archive_dir, exist_ok=True)
        out_path = os.path.join(
            settings.options_flow_archive_dir,
            f"options_flow_{date.today().isoformat()}.jsonl",
        )
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(OptionsFlow).where(OptionsFlow.timestamp < cutoff)
            )).scalars().all()

            if not rows:
                return 0

            with open(out_path, "a") as fh:
                for r in rows:
                    fh.write(json.dumps({
                        "id": r.id,
                        "ticker": r.ticker,
                        "strike": float(r.strike),
                        "expiry": r.expiry.isoformat(),
                        "right": r.right,
                        "exchange": r.exchange,
                        "timestamp": r.timestamp.isoformat(),
                        "premium": float(r.premium),
                        "size": r.size,
                        "trade_type": r.trade_type,
                        "sentiment": r.sentiment,
                        "iv": float(r.iv) if r.iv is not None else None,
                        "delta": float(r.delta) if r.delta is not None else None,
                        "dte": r.dte,
                        "relative_volume": float(r.relative_volume)
                        if r.relative_volume is not None else None,
                        "sweep_confirmed": r.sweep_confirmed,
                        "large_sweep": r.large_sweep,
                    }, default=str) + "\n")
                    archived += 1

            for r in rows:
                await session.delete(r)
            await session.commit()
        logger.info("Archived %d options_flow rows to %s", archived, out_path)
    except Exception as exc:
        logger.warning("Options flow archive failed: %s", exc)
    return archived


# Module-level singleton — imported by main.py lifespan
options_flow_ingest = OptionsFlowIngestService()
