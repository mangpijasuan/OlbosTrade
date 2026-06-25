"""
Lightweight in-process observability.

Deliberately NOT a full tracing stack — just counters, gauges, and a small ring
of recent events, held in memory. Enough to answer "is the scanner running, how
many signals did it block and why, when was the last fill" from a single
endpoint, with zero external dependencies. Resets on restart (this is live
operational state, not the system of record — the DB is).

Thread-safe via a single lock; cheap enough to call on every scan / route / fill.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Deque, Optional


class Observability:
    def __init__(self, ring_size: int = 100) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._events: Deque[dict] = deque(maxlen=ring_size)
        self._lock = Lock()
        self._started = time.time()

    # ── writes ──────────────────────────────────────────────────────────────
    def incr(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + n

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = float(value)

    def event(self, name: str, **fields: Any) -> None:
        rec = {"ts": time.time(), "name": name, **fields}
        with self._lock:
            self._events.append(rec)

    # ── reads ───────────────────────────────────────────────────────────────
    def counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def recent(self, limit: int = 20, name: Optional[str] = None) -> list[dict]:
        with self._lock:
            items = list(self._events)
        if name is not None:
            items = [e for e in items if e["name"] == name]
        return items[-limit:][::-1]   # newest first

    def snapshot(self, recent_limit: int = 20) -> dict:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            events = list(self._events)[-recent_limit:][::-1]
            uptime = time.time() - self._started
        return {
            "uptime_seconds": round(uptime, 1),
            "counters": counters,
            "gauges": gauges,
            "recent_events": events,
            "event_count": len(events),
        }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._events.clear()
            self._started = time.time()


# Process-wide singleton.
observability = Observability()
