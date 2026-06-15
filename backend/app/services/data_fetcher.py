"""
Historical market data fetcher.
Pulls OHLCV via yfinance, options chains via broker, caches to DB.
Calculates IV Rank and IV Percentile from historical data.
Scheduled daily refresh at 6:30am ET via APScheduler.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.broker_interface import BrokerInterface, OptionsChain
from app.core.database import AsyncSessionLocal
from app.models.backtest_result import MarketSnapshot

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class DataFetcher:
    """
    Fetches, calculates, and caches all market data the platform needs.
    Depends on an injected BrokerInterface for live options chain data.
    """

    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    # ── OHLCV ───────────────────────────────────────────────────────────────

    async def fetch_ohlcv(
        self, symbol: str, start: str, end: str
    ) -> pd.DataFrame:
        """
        Fetch daily OHLCV via the connected broker (IBKR/Alpaca).
        Falls back to yfinance only if broker fails.

        Args:
            symbol: Ticker symbol (e.g. "SPY")
            start:  Start date "YYYY-MM-DD"
            end:    End date   "YYYY-MM-DD"

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume, Date index.
        """
        # ── Primary: broker historical bars ──────────────────────────────────
        try:
            from datetime import date as _date
            start_d = _date.fromisoformat(start)
            end_d   = _date.fromisoformat(end)
            days    = (end_d - start_d).days + 60   # +60 for indicator warm-up
            bars    = await self.broker.get_bars(symbol, timeframe="1Day", limit=days, end_date=end)

            if bars:
                df = pd.DataFrame([
                    {
                        "Date":   b.timestamp.date() if hasattr(b.timestamp, "date") else b.timestamp,
                        "Open":   float(b.open),
                        "High":   float(b.high),
                        "Low":    float(b.low),
                        "Close":  float(b.close),
                        "Volume": b.volume,
                    }
                    for b in bars
                ])
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.set_index("Date").sort_index()

                # Filter to requested window
                df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]

                if not df.empty:
                    logger.info("Fetched %d OHLCV rows for %s via broker", len(df), symbol)
                    return df
        except Exception as broker_exc:
            logger.warning("Broker OHLCV fetch failed for %s (%s) — trying yfinance", symbol, broker_exc)

        # ── Fallback: yfinance ────────────────────────────────────────────────
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, auto_adjust=True)

        if df.empty:
            raise ValueError(f"No OHLCV data for {symbol} from {start} to {end} (broker + yfinance both failed)")

        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index.name = "Date"

        logger.info("Fetched %d OHLCV rows for %s via yfinance", len(df), symbol)
        return df

    # ── Options chain ────────────────────────────────────────────────────────

    async def fetch_options_chain(self, symbol: str, expiry: str) -> OptionsChain:
        """
        Fetch live options chain via the injected broker interface.

        Args:
            symbol: Underlying ticker
            expiry: Expiration date "YYYY-MM-DD"
        """
        chain = await self.broker.get_options_chain(symbol, expiry)
        logger.info(
            "Fetched options chain for %s %s — %d calls, %d puts",
            symbol, expiry, len(chain.calls), len(chain.puts),
        )
        return chain

    # ── DB caching ───────────────────────────────────────────────────────────

    async def cache_to_db(
        self, symbol: str, df: pd.DataFrame, session: AsyncSession
    ) -> None:
        """
        Persist OHLCV rows as MarketSnapshot records.
        Existing rows for the same symbol + timestamp are not duplicated
        (upsert by insert-if-not-exists logic).

        Args:
            symbol: Ticker symbol
            df:     OHLCV DataFrame from fetch_ohlcv()
            session: Active async DB session
        """
        rows_added = 0
        for ts, row in df.iterrows():
            ts_dt = ts.to_pydatetime()
            # Skip if a snapshot already exists for this symbol + timestamp
            existing = await session.execute(
                select(MarketSnapshot.id).where(
                    MarketSnapshot.symbol == symbol,
                    MarketSnapshot.timestamp == ts_dt,
                ).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                continue

            snapshot = MarketSnapshot(
                symbol=symbol,
                timestamp=ts_dt,
                price=float(row["Close"]),
            )
            session.add(snapshot)
            rows_added += 1

        await session.flush()
        logger.info("Cached %d new MarketSnapshot rows for %s", rows_added, symbol)

    # ── IV calculations ──────────────────────────────────────────────────────

    def calculate_iv_rank(
        self, iv_series: pd.Series, lookback: int = 252
    ) -> float:
        """
        IV Rank = (current IV - 52w low) / (52w high - 52w low) * 100

        Args:
            iv_series: Historical IV values (most recent last)
            lookback:  Trading days to look back (default: 252 = 1 year)

        Returns:
            IV Rank as float 0–100. Returns 0.0 if range is zero.
        """
        if len(iv_series) < 2:
            return 0.0

        window = iv_series.iloc[-lookback:] if len(iv_series) >= lookback else iv_series
        current = float(window.iloc[-1])
        low = float(window.min())
        high = float(window.max())

        if high == low:
            return 0.0

        return round(((current - low) / (high - low)) * 100, 2)

    def calculate_iv_percentile(
        self, iv_series: pd.Series, lookback: int = 252
    ) -> float:
        """
        IV Percentile = % of days in lookback where IV was below current IV.

        Args:
            iv_series: Historical IV values (most recent last)
            lookback:  Trading days to look back

        Returns:
            IV Percentile as float 0–100.
        """
        if len(iv_series) < 2:
            return 0.0

        window = iv_series.iloc[-lookback:] if len(iv_series) >= lookback else iv_series
        current = float(window.iloc[-1])
        pct = float((window < current).mean() * 100)
        return round(pct, 2)

    # ── Technical indicators ─────────────────────────────────────────────────

    def calculate_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        """Wilder's RSI."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def calculate_sma(self, close: pd.Series, period: int = 20) -> pd.Series:
        """Simple moving average."""
        return close.rolling(window=period).mean()

    def calculate_realized_vol(
        self, close: pd.Series, period: int = 20, annualize: bool = True
    ) -> pd.Series:
        """
        Historical realized volatility as annualized standard deviation
        of log returns.
        """
        log_returns = np.log(close / close.shift(1))
        rv = log_returns.rolling(period).std()
        if annualize:
            rv = rv * np.sqrt(252)
        return rv


# ── Scheduler ────────────────────────────────────────────────────────────────

def create_data_scheduler(fetcher: DataFetcher) -> AsyncIOScheduler:
    """
    Create an APScheduler that refreshes SPY market data daily at 6:30am ET.
    Call scheduler.start() when the FastAPI app starts.
    """
    scheduler = AsyncIOScheduler(timezone=ET)

    async def daily_refresh() -> None:
        logger.info("Daily data refresh starting...")
        end = datetime.now(ET).strftime("%Y-%m-%d")
        start = (datetime.now(ET) - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            df = await fetcher.fetch_ohlcv("SPY", start, end)
            async with AsyncSessionLocal() as session:
                await fetcher.cache_to_db("SPY", df, session)
                await session.commit()
            logger.info("Daily refresh complete — %d SPY rows cached", len(df))
        except Exception as exc:
            logger.error("Daily refresh failed: %s", exc)

    scheduler.add_job(
        daily_refresh,
        trigger="cron",
        hour=6,
        minute=30,
        id="daily_spy_refresh",
        replace_existing=True,
    )
    return scheduler
