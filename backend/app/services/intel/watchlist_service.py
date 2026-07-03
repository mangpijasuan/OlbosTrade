"""
Smart Watchlist service — CRUD + default seeding.

Replaces the hardcoded ticker arrays scattered across the UI with a real,
user-editable model. System lists (is_system=True) are seeded once and cannot
be deleted, but users can add their own.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.watchlist import Watchlist, WatchlistSymbol
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Default system watchlists (slug, name, description, symbols).
_DEFAULTS: list[tuple[str, str, str, list[str]]] = [
    ("core-index-options", "Core Index Options", "Liquid index ETFs for spreads", ["SPY", "QQQ", "IWM", "DIA"]),
    ("magnificent-seven", "Magnificent Seven", "Mega-cap tech leaders", ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]),
    ("options-liquid", "Options Liquid Universe", "Tight-spread optionable names", ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "AMZN", "META"]),
    ("wheel-candidates", "Wheel Candidates", "Steady names for CSP/covered calls", ["KO", "PFE", "T", "INTC", "F", "VZ", "WBA", "KMI"]),
    ("etf-rotation", "ETF Rotation", "Sector/asset rotation ETFs", ["XLK", "XLF", "XLE", "XLV", "GLD", "TLT", "USO"]),
    ("earnings-watch", "Earnings Watch", "Upcoming earnings movers", ["NVDA", "AAPL", "MSFT", "AMZN", "META"]),
    ("macro-risk-watch", "Macro Risk Watch", "Rates/vol/USD proxies", ["TLT", "UUP", "GLD", "VIXY", "SPY"]),
    ("semis", "Technology & Semiconductors", "Semiconductor complex", ["NVDA", "AMD", "AVGO", "SMH", "TSM", "MU"]),
    ("defensive", "Defensive Assets", "Lower-beta / safe-haven", ["GLD", "TLT", "XLU", "XLP", "KO"]),
]


async def seed_defaults() -> int:
    """Idempotently ensure system watchlists exist. Returns count created."""
    created = 0
    async with AsyncSessionLocal() as session:
        existing = set(
            (await session.execute(select(Watchlist.slug))).scalars().all()
        )
        for slug, name, desc, symbols in _DEFAULTS:
            if slug in existing:
                continue
            wl = Watchlist(name=name, slug=slug, description=desc, is_system=True)
            wl.symbols = [WatchlistSymbol(symbol=s, asset_class="equity") for s in symbols]
            session.add(wl)
            created += 1
        if created:
            await session.commit()
            logger.info("Seeded %d default watchlists", created)
    return created


async def list_watchlists() -> list[dict]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Watchlist).order_by(Watchlist.is_system.desc(), Watchlist.name)
        )).scalars().all()
        return [_serialize(w) for w in rows]


async def get_watchlist(slug: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        w = (await session.execute(
            select(Watchlist).where(Watchlist.slug == slug)
        )).scalars().first()
        return _serialize(w) if w else None


async def create_watchlist(name: str, description: str, symbols: list[str]) -> dict:
    slug = _slugify(name)
    async with AsyncSessionLocal() as session:
        wl = Watchlist(name=name, slug=slug, description=description, is_system=False)
        wl.symbols = [WatchlistSymbol(symbol=s.upper(), asset_class="equity") for s in symbols]
        session.add(wl)
        await session.commit()
        await session.refresh(wl)
        return _serialize(wl)


async def add_symbol(slug: str, symbol: str, asset_class: str = "equity") -> dict | None:
    async with AsyncSessionLocal() as session:
        w = (await session.execute(
            select(Watchlist).where(Watchlist.slug == slug)
        )).scalars().first()
        if not w:
            return None
        if symbol.upper() not in {s.symbol for s in w.symbols}:
            w.symbols.append(WatchlistSymbol(symbol=symbol.upper(), asset_class=asset_class))
            await session.commit()
            await session.refresh(w)
        return _serialize(w)


async def remove_symbol(slug: str, symbol: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        w = (await session.execute(
            select(Watchlist).where(Watchlist.slug == slug)
        )).scalars().first()
        if not w:
            return None
        for s in list(w.symbols):
            if s.symbol == symbol.upper():
                await session.delete(s)
        await session.commit()
        await session.refresh(w)
        return _serialize(w)


async def delete_watchlist(slug: str) -> bool:
    """Delete a user watchlist. System lists are protected."""
    async with AsyncSessionLocal() as session:
        w = (await session.execute(
            select(Watchlist).where(Watchlist.slug == slug)
        )).scalars().first()
        if not w or w.is_system:
            return False
        await session.delete(w)
        await session.commit()
        return True


def _serialize(w: Watchlist) -> dict:
    return {
        "slug": w.slug,
        "name": w.name,
        "description": w.description,
        "is_system": w.is_system,
        "symbols": [{"symbol": s.symbol, "asset_class": s.asset_class} for s in w.symbols],
    }


def _slugify(name: str) -> str:
    import re
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "list"
    return f"{base}-{abs(hash(name)) % 10000}"
