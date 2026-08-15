"""
IBKRRequestCoordinator — single chokepoint for every call that touches the
shared IBKR connection.

`get_broker()` (broker_factory.py) is a process-wide singleton wrapping
exactly one `ib_insync.IB()` object — one TCP socket to TWS/Gateway, shared
by every caller. ib_insync's own client throttles outgoing *message rate*
(45/sec) but has no priority concept: whichever caller enqueues first is
served first. A background scan job that fires dozens of option-chain
requests can make a single interactive user request queue behind all of
them for minutes — this is what broke `GET /api/market/options-chain/{symbol}`
during live verification.

Design: three priority queues (P0 > P1 > P2) drained by a small worker
pool. One worker is *reserved* and only ever pulls P0/P1 — this bounds
worst-case queueing delay for interactive/critical requests even when the
other workers are saturated with P2 batch work. This is not a preemptive
scheduler: a single in-flight IBKR call (e.g. one sequential chain fetch)
cannot be interrupted mid-flight, so the reserved worker bounds *queueing*
time, not in-flight duration — see the batched get_options_chain in
ibkr_client.py for the in-flight-duration side of this fix.

Requests are deduplicated by an optional `key`: concurrent callers asking
for the same thing (e.g. "chain:SPY:2026-09-18") share one in-flight IBKR
round-trip instead of issuing duplicates.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Awaitable, Callable, Optional, TypeVar

from app.services.observability import observability
from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

DEFAULT_TIMEOUT_SECONDS = 30.0
# ib_insync's own Client already caps outgoing message *rate* (45/sec)
# regardless of how many coordinator workers exist, so a larger worker pool
# doesn't risk violating IBKR pacing — it just controls how much P2 (scanner)
# throughput is available. 6 workers roughly matches the background scanners'
# pre-existing Semaphore(equity_scan_concurrency=8) so P2 throughput isn't
# badly regressed when P0/P1 are idle (the common case).
NUM_WORKERS = 6
# Worker indices below this are reserved for P0/P1 only — they never pull P2,
# so background batch work can't fully starve interactive/critical requests.
NUM_RESERVED_WORKERS = 2
# How long an idle worker sleeps between priority-queue polls. Request volume
# here is low (a handful of IBKR calls per minute, not a hot path), so a
# simple poll is far simpler and more obviously correct than a cancellable
# multi-queue wait — and 20ms is negligible next to IBKR round-trip times.
_POLL_INTERVAL_SECONDS = 0.02


class Priority(IntEnum):
    """Lower value = served first."""
    P0 = 0  # order execution, account/position sync, risk checks
    P1 = 1  # interactive user requests (options chain, active screens)
    P2 = 2  # background scanners, research jobs


@dataclass
class _Job:
    priority: Priority
    fn: Callable[[], Awaitable[Any]]
    future: "asyncio.Future"
    queued_at: float
    req_type: str
    symbol: Optional[str]


class IBKRRequestCoordinator:
    """Owns request fairness, dedup, and reconnect serialization for the
    shared IBKR connection. See module docstring."""

    def __init__(self, num_workers: int = NUM_WORKERS, num_reserved: int = NUM_RESERVED_WORKERS) -> None:
        self._queues: dict[Priority, "asyncio.Queue[_Job]"] = {
            Priority.P0: asyncio.Queue(),
            Priority.P1: asyncio.Queue(),
            Priority.P2: asyncio.Queue(),
        }
        self._num_workers = num_workers
        self._num_reserved = num_reserved
        self._in_flight: dict[str, "asyncio.Future"] = {}
        self._in_flight_lock = asyncio.Lock()
        # Guards broker.connect() so overlapping reconnect attempts (e.g. the
        # 60s scheduler check racing a request-triggered reconnect) can't
        # spawn duplicate connection attempts.
        self.reconnect_lock = asyncio.Lock()
        self._workers: Optional[list["asyncio.Task"]] = None
        self._loop: Optional["asyncio.AbstractEventLoop"] = None
        self._active_count = 0
        self._active_lock = asyncio.Lock()

    def start(self) -> None:
        """Spawn the worker pool for the currently running event loop.

        Idempotent for repeated calls *on the same loop* — safe to call
        from every submit(). But a worker `Task` is permanently bound to
        the loop it was created on; if this is ever called from a
        *different* running loop than last time (the FastAPI app only has
        one for its whole process lifetime, so this shouldn't happen there,
        but it's exactly what a test suite's per-test event loop does, and
        it's cheap to make actually safe rather than silently hang), the
        old workers can never service new requests again. Detect that and
        respawn fresh workers/queues bound to the current loop instead of
        leaving callers waiting on a queue nothing will ever drain.
        """
        current_loop = asyncio.get_event_loop()
        if self._workers is not None and self._loop is current_loop:
            return
        if self._workers is not None:
            # Task.cancel() schedules the cancellation via call_soon() on
            # the task's OWN loop — if that loop is already closed (the
            # common case here: a previous test's per-test loop), that
            # call_soon() raises RuntimeError synchronously instead of
            # just being a no-op. A closed loop will never run those tasks
            # again regardless, so there's nothing to actually cancel.
            if self._loop is not None and not self._loop.is_closed():
                for w in self._workers:
                    w.cancel()
            self._queues = {p: asyncio.Queue() for p in Priority}
            self._in_flight.clear()
            self._in_flight_lock = asyncio.Lock()
            self.reconnect_lock = asyncio.Lock()
            self._active_lock = asyncio.Lock()
            self._active_count = 0

        self._loop = current_loop
        self._workers = [
            asyncio.create_task(self._worker_loop(reserved=(i < self._num_reserved)))
            for i in range(self._num_workers)
        ]

    async def submit(
        self,
        priority: Priority,
        fn: Callable[[], Awaitable[T]],
        *,
        key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        req_type: str = "generic",
        symbol: Optional[str] = None,
    ) -> T:
        """Queue fn for execution against the shared IBKR connection.

        key: dedup key (e.g. "chain:SPY:2026-09-18"). If a request with the
        same key is already in-flight, this call awaits that same result
        instead of enqueueing a duplicate IBKR round-trip.
        """
        self.start()

        if key is not None:
            async with self._in_flight_lock:
                existing = self._in_flight.get(key)
                if existing is not None and not existing.done():
                    observability.incr(f"ibkr.request.{priority.name.lower()}.dedup")
                    return await asyncio.wait_for(asyncio.shield(existing), timeout=timeout)
                future: "asyncio.Future" = asyncio.get_event_loop().create_future()
                self._in_flight[key] = future
        else:
            future = asyncio.get_event_loop().create_future()

        job = _Job(
            priority=priority, fn=fn, future=future, queued_at=time.monotonic(),
            req_type=req_type, symbol=symbol,
        )
        observability.incr(f"ibkr.request.{priority.name.lower()}.submitted")
        await self._queues[priority].put(job)
        observability.gauge(f"ibkr.queue_depth.{priority.name.lower()}", self._queues[priority].qsize())

        try:
            # shield: if THIS caller's wait times out, don't cancel the
            # underlying job — other callers (dedup) or the log/observability
            # bookkeeping in _run_job should still see it through.
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError:
            observability.incr(f"ibkr.request.{priority.name.lower()}.timeout")
            logger.warning(
                "IBKR REQUEST symbol=%s type=%s priority=%s status=timeout after=%.1fs",
                symbol, req_type, priority.name, timeout,
            )
            # Bare TimeoutError() stringifies to "" — a route that does
            # str(exc) on it (as the options-chain route does) would
            # surface a blank, useless error to the caller. Carry a real
            # message instead.
            raise asyncio.TimeoutError(
                f"IBKR request timed out after {timeout:.0f}s "
                f"(priority={priority.name}, type={req_type}, symbol={symbol})"
            ) from None
        finally:
            if key is not None:
                async with self._in_flight_lock:
                    if self._in_flight.get(key) is future:
                        del self._in_flight[key]

    async def _worker_loop(self, reserved: bool) -> None:
        """reserved=True workers only ever pull P0/P1."""
        priorities: tuple[Priority, ...] = (
            (Priority.P0, Priority.P1) if reserved else (Priority.P0, Priority.P1, Priority.P2)
        )
        while True:
            job = await self._get_next_job(priorities)
            await self._run_job(job)

    async def _get_next_job(self, priorities: tuple[Priority, ...]) -> _Job:
        while True:
            for p in priorities:
                try:
                    return self._queues[p].get_nowait()
                except asyncio.QueueEmpty:
                    continue
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _run_job(self, job: _Job) -> None:
        queue_wait_ms = (time.monotonic() - job.queued_at) * 1000
        started = time.monotonic()
        async with self._active_lock:
            self._active_count += 1
            observability.gauge("ibkr.active_requests", self._active_count)

        status = "success"
        try:
            result = await job.fn()
            if not job.future.done():
                job.future.set_result(result)
        except Exception as exc:  # noqa: BLE001 — propagated to the caller via the future
            status = "error"
            if not job.future.done():
                job.future.set_exception(exc)
        finally:
            async with self._active_lock:
                self._active_count -= 1
                observability.gauge("ibkr.active_requests", self._active_count)
            exec_ms = (time.monotonic() - started) * 1000
            observability.incr(f"ibkr.request.{job.priority.name.lower()}.completed")
            observability.gauge(
                f"ibkr.queue_depth.{job.priority.name.lower()}", self._queues[job.priority].qsize()
            )
            logger.info(
                "IBKR REQUEST symbol=%s type=%s priority=%s queue_wait=%dms execution=%dms status=%s",
                job.symbol, job.req_type, job.priority.name, queue_wait_ms, exec_ms, status,
            )

    def health_snapshot(self) -> dict:
        """Point-in-time coordinator state for GET /api/health/detail."""
        return {
            "workers": self._num_workers,
            "reserved_workers": self._num_reserved,
            "active_requests": self._active_count,
            "queue_depth": {p.name: self._queues[p].qsize() for p in Priority},
            "in_flight_dedup_keys": len(self._in_flight),
        }


# Process-wide singleton — matches broker_factory.get_broker()'s existing
# singleton pattern.
ibkr_coordinator = IBKRRequestCoordinator()
