"""
Free options-flow snapshot — unusual activity from yfinance option chains.

This is the FREE, real-data complement to the premium OPRA stream in
options_flow_ingest.py. It scans option chains for the watchlist, flags strikes
where volume materially exceeds open interest ("volume » open interest"), and
writes them to the same options_flow table the UI already reads.

Data is delayed (~15 min) and free — never presented as a real-time OPRA tape.
It replaces synthetic demo ticks with genuine market data.

Snapshot semantics: each run REPLACES the prior snapshot rows (exchange tag
``yfinance-snapshot``) so the table holds the latest picture rather than an
ever-growing tape. The premium OPRA stream, if ever enabled, is untouched.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.options_flow import OptionsFlow
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SNAPSHOT_TAG = "yfinance-snapshot"


def _scan_symbol(symbol: str, max_dte: int, min_vol_oi: float, min_premium: float) -> list[dict]:
    """Blocking yfinance scan for one symbol. Returns unusual-activity rows."""
    import yfinance as yf  # type: ignore
    import pandas as pd    # type: ignore

    rows: list[dict] = []
    try:
        tk = yf.Ticker(symbol)
        expiries = list(tk.options or [])
    except Exception as exc:
        logger.warning("chain list failed for %s: %s", symbol, exc)
        return rows

    today = datetime.now(timezone.utc).date()
    for exp_str in expiries:
        try:
            exp = date.fromisoformat(exp_str)
        except Exception:
            continue
        dte = (exp - today).days
        if dte < 0 or dte > max_dte:
            continue
        try:
            chain = tk.option_chain(exp_str)
        except Exception:
            continue

        for right, df in (("C", chain.calls), ("P", chain.puts)):
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                try:
                    volume = int(r.get("volume") or 0)
                    oi = int(r.get("openInterest") or 0)
                    last = float(r.get("lastPrice") or 0.0)
                    if volume <= 0 or last <= 0:
                        continue
                    vol_oi = volume / oi if oi > 0 else float(volume)  # no OI = fully unusual
                    premium = volume * last * 100.0
                    if vol_oi < min_vol_oi or premium < min_premium:
                        continue
                    iv = r.get("impliedVolatility")
                    rows.append({
                        "ticker": symbol,
                        "strike": Decimal(str(round(float(r["strike"]), 2))),
                        "expiry": exp,
                        "right": right,
                        "premium": Decimal(str(round(premium, 2))),
                        "size": volume,
                        "iv": Decimal(str(round(float(iv), 6))) if iv and not pd.isna(iv) else None,
                        "dte": dte,
                        "relative_volume": Decimal(str(round(vol_oi, 4))),
                        # Snapshot heuristics (no tape): calls lean bullish, puts bearish.
                        "sentiment": "bullish" if right == "C" else "bearish",
                        "trade_type": "block" if volume >= settings.options_flow_block_min_size else "single",
                        "large_sweep": premium >= settings.options_flow_large_sweep_premium,
                        "sweep_confirmed": False,  # cannot confirm sweeps without a tape
                    })
                except Exception:
                    continue
    return rows


async def run_snapshot() -> int:
    """Scan the watchlist and replace the current snapshot rows. Returns count."""
    if not settings.options_flow_free_snapshot_enabled:
        return 0

    symbols = settings.get_options_flow_watchlist()
    loop = asyncio.get_running_loop()
    all_rows: list[dict] = []
    for sym in symbols:
        rows = await loop.run_in_executor(
            None, _scan_symbol, sym,
            settings.options_flow_max_dte,
            settings.options_flow_snapshot_min_vol_oi,
            settings.options_flow_snapshot_min_premium,
        )
        all_rows.extend(rows)

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        # Replace prior snapshot (leave any real OPRA rows untouched).
        await session.execute(delete(OptionsFlow).where(OptionsFlow.exchange == _SNAPSHOT_TAG))
        for r in all_rows:
            session.add(OptionsFlow(exchange=_SNAPSHOT_TAG, timestamp=now, **r))
        await session.commit()

    logger.info("Free options-flow snapshot: %d unusual rows across %d symbols",
                len(all_rows), len(symbols))
    return len(all_rows)
