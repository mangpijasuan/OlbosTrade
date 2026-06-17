"""
Async Redis client + lightweight pub/sub helper.

OlbosQuant ships a ``redis`` dependency and a ``redis_url`` setting but, until
the Options Flow module, nothing in the app actually used Redis. This module
provides exactly what that module needs — a JSON pub/sub channel to fan out
live option-flow ticks to WebSocket clients — and nothing more.

Design notes:
  - ``get_redis()`` lazily connects a single shared ``redis.asyncio`` client.
  - If Redis is unreachable (common in dev / single-container deploys), the
    helpers transparently fall back to an in-process asyncio pub/sub broker so
    WebSocket fanout still works *within one Uvicorn worker*. Cross-process /
    multi-worker fanout requires a real Redis server.
  - All public helpers are no-throw: a broken Redis never takes down a request
    or the ingest loop.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator, Optional

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

try:  # redis>=4.2 ships the asyncio client under redis.asyncio
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover - dependency always present in prod
    aioredis = None  # type: ignore


# ── In-process fallback broker ──────────────────────────────────────────────
class _InProcessBroker:
    """
    Minimal asyncio pub/sub used when Redis is unavailable. Each subscriber
    gets its own bounded queue; slow consumers drop the oldest message rather
    than blocking publishers (live flow is fire-and-forget).
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, channel: str, message: str) -> None:
        for q in list(self._subs.get(channel, ())):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[channel].add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs[channel].discard(q)


_inprocess = _InProcessBroker()
_redis_client: "Optional[aioredis.Redis]" = None
_redis_ok: Optional[bool] = None  # None = untried, True/False = last known state


async def get_redis() -> "Optional[aioredis.Redis]":
    """Return a connected Redis client, or None if unavailable (cached)."""
    global _redis_client, _redis_ok

    if _redis_ok is False:
        return None
    if _redis_client is not None:
        return _redis_client
    if aioredis is None:
        _redis_ok = False
        return None

    try:
        client = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        await client.ping()
        _redis_client = client
        _redis_ok = True
        logger.info("Redis connected — %s", settings.redis_url)
        return client
    except Exception as exc:
        _redis_ok = False
        logger.warning(
            "Redis unavailable (%s) — using in-process pub/sub fallback", exc
        )
        return None


async def publish_json(channel: str, payload: Any) -> None:
    """Publish a JSON-serialisable payload to a channel. Never raises."""
    try:
        message = json.dumps(payload, default=str)
    except Exception as exc:
        logger.warning("publish_json: could not serialise payload: %s", exc)
        return

    client = await get_redis()
    if client is not None:
        try:
            await client.publish(channel, message)
            return
        except Exception as exc:
            logger.warning("Redis publish failed (%s) — falling back", exc)
    await _inprocess.publish(channel, message)


async def subscribe_json(channel: str) -> AsyncIterator[dict]:
    """
    Async iterator over decoded JSON messages on a channel.

    Uses Redis if available, otherwise the in-process broker. Malformed
    messages are skipped rather than raising.
    """
    client = await get_redis()
    if client is not None:
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for raw in pubsub.listen():
                if raw is None or raw.get("type") != "message":
                    continue
                data = raw.get("data")
                try:
                    yield json.loads(data)
                except Exception:
                    continue
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
        return

    async for raw in _inprocess.subscribe(channel):
        try:
            yield json.loads(raw)
        except Exception:
            continue


async def close_redis() -> None:
    """Close the shared client on shutdown."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception:
            pass
        _redis_client = None
