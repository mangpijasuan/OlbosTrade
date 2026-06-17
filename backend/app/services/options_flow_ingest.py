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
