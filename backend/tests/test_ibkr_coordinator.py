"""
Unit tests for IBKRRequestCoordinator — priority ordering, dedup, timeout,
and reconnect-lock behavior. No live IBKR connection; every "IBKR call" is a
fake async function with a controlled delay so ordering/timing is
deterministic rather than dependent on real network latency.

These are white-box tests of an internal coordination class (private
attributes/methods are accessed directly for the priority-ordering test,
where that's the only deterministic way to assert queue-selection order
without racing the worker pool's own scheduling).

Run with: pytest tests/test_ibkr_coordinator.py -v
"""

import asyncio
import time

import pytest

from app.broker.ibkr_coordinator import IBKRRequestCoordinator, Priority, _Job
from app.utils.request_context import request_id_var


@pytest.fixture
async def make_coordinator():
    """Factory fixture — each test creates its own coordinator instance(s)
    (never the process-wide singleton) so tests don't interfere with each
    other, and every spawned worker task is cancelled at teardown so no
    background loop leaks past the test into a later one."""
    created: list[IBKRRequestCoordinator] = []

    def _make(**kwargs):
        c = IBKRRequestCoordinator(**kwargs)
        created.append(c)
        return c

    yield _make

    for c in created:
        if c._workers:
            for w in c._workers:
                w.cancel()
            await asyncio.gather(*c._workers, return_exceptions=True)


@pytest.mark.asyncio
async def test_get_next_job_respects_priority_order(make_coordinator):
    """The worker's queue-selection logic must drain P0 before P1 before P2
    when all three already have work queued."""
    coordinator = make_coordinator(num_workers=1, num_reserved=0)

    async def noop():
        return None

    for p in (Priority.P2, Priority.P1, Priority.P0):  # deliberately out of order
        job = _Job(
            priority=p, fn=noop, future=asyncio.get_event_loop().create_future(),
            queued_at=time.monotonic(), req_type="test", symbol=None,
        )
        coordinator._queues[p].put_nowait(job)

    order = []
    for _ in range(3):
        job = await coordinator._get_next_job((Priority.P0, Priority.P1, Priority.P2))
        order.append(job.priority)

    assert order == [Priority.P0, Priority.P1, Priority.P2]


@pytest.mark.asyncio
async def test_dedup_shares_single_in_flight_call(make_coordinator):
    """Two concurrent submits with the same key must share one underlying
    call instead of issuing a duplicate IBKR round-trip."""
    coordinator = make_coordinator(num_workers=2, num_reserved=1)
    call_count = 0

    async def slow_fetch():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return "result"

    results = await asyncio.gather(
        coordinator.submit(Priority.P1, slow_fetch, key="chain:SPY:2026-09-18", timeout=5),
        coordinator.submit(Priority.P1, slow_fetch, key="chain:SPY:2026-09-18", timeout=5),
    )

    assert call_count == 1
    assert results == ["result", "result"]


@pytest.mark.asyncio
async def test_dedup_does_not_share_across_different_keys(make_coordinator):
    """Different dedup keys must not be conflated into one shared call."""
    coordinator = make_coordinator(num_workers=2, num_reserved=1)
    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return call_count

    r1 = await coordinator.submit(Priority.P1, fetch, key="chain:SPY:2026-09-18", timeout=5)
    r2 = await coordinator.submit(Priority.P1, fetch, key="chain:QQQ:2026-09-18", timeout=5)

    assert call_count == 2
    assert r1 != r2


@pytest.mark.asyncio
async def test_reserved_worker_prevents_p1_starvation_under_p2_load(make_coordinator):
    """A P1 request must not queue behind a flood of slow P2 background
    work — the reserved worker(s) never pull P2 at all."""
    coordinator = make_coordinator(num_workers=2, num_reserved=1)

    async def slow_p2():
        await asyncio.sleep(1.0)
        return "p2-done"

    # Flood P2 with enough work to occupy the one shared worker well past
    # this test's own deadline.
    p2_futures = [
        asyncio.ensure_future(coordinator.submit(Priority.P2, slow_p2, timeout=5))
        for _ in range(5)
    ]
    await asyncio.sleep(0.05)  # let the flood actually start occupying workers

    async def fast_p1():
        return "p1-done"

    start = time.monotonic()
    result = await asyncio.wait_for(
        coordinator.submit(Priority.P1, fast_p1, timeout=5), timeout=0.5
    )
    elapsed = time.monotonic() - start

    assert result == "p1-done"
    assert elapsed < 0.3, "P1 request waited on P2 background work despite the reserved worker"

    for f in p2_futures:
        f.cancel()


@pytest.mark.asyncio
async def test_submit_raises_timeout_error_when_fn_never_completes(make_coordinator):
    coordinator = make_coordinator(num_workers=1, num_reserved=1)

    async def hang_forever():
        await asyncio.sleep(10)
        return "never"

    with pytest.raises(asyncio.TimeoutError):
        await coordinator.submit(Priority.P0, hang_forever, timeout=0.1)


@pytest.mark.asyncio
async def test_submit_propagates_exceptions_from_fn(make_coordinator):
    coordinator = make_coordinator(num_workers=1, num_reserved=1)

    async def boom():
        raise ValueError("broker said no")

    with pytest.raises(ValueError, match="broker said no"):
        await coordinator.submit(Priority.P0, boom, timeout=5)


@pytest.mark.asyncio
async def test_reconnect_lock_prevents_overlapping_reconnects(make_coordinator):
    coordinator = make_coordinator(num_workers=1, num_reserved=1)
    concurrent_count = 0
    max_concurrent = 0

    async def fake_reconnect():
        nonlocal concurrent_count, max_concurrent
        async with coordinator.reconnect_lock:
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1

    await asyncio.gather(fake_reconnect(), fake_reconnect(), fake_reconnect())

    assert max_concurrent == 1


@pytest.mark.asyncio
async def test_health_snapshot_reports_worker_and_queue_shape(make_coordinator):
    coordinator = make_coordinator(num_workers=3, num_reserved=1)
    snap = coordinator.health_snapshot()

    assert snap["workers"] == 3
    assert snap["reserved_workers"] == 1
    assert set(snap["queue_depth"].keys()) == {"P0", "P1", "P2"}
    assert snap["active_requests"] == 0
    assert snap["in_flight_dedup_keys"] == 0


def test_start_recovers_when_reused_across_event_loops():
    """Regression test for a real bug this suite caught in CI: a worker
    Task is permanently bound to the event loop it was created on. The
    process-wide coordinator singleton only ever sees one loop in the
    real FastAPI app (one process, one loop, for the app's whole
    lifetime) — but reusing the *same* coordinator instance across
    separate event loops (exactly what pytest-asyncio's default per-test
    event loop does, which is how this was first caught: every test in
    test_account_guard.py after the first one hung indefinitely) used to
    leave later callers waiting on workers stuck on an already-closed
    loop that could never service them. start() must detect the loop
    change and respawn fresh workers instead.

    Deliberately not using the make_coordinator fixture — this test
    manages raw event loops itself to reproduce the exact failure mode.
    """
    coordinator = IBKRRequestCoordinator(num_workers=2, num_reserved=1)

    async def fn():
        return "ok"

    for _ in range(3):
        loop = asyncio.new_event_loop()
        try:
            # Each iteration's own asyncio.wait_for bounds it to a few
            # seconds — if the fix regresses, this fails fast with
            # TimeoutError instead of hanging the whole test run again.
            result = loop.run_until_complete(
                asyncio.wait_for(coordinator.submit(Priority.P0, fn, timeout=2), timeout=3)
            )
            assert result == "ok"
        finally:
            if coordinator._workers:
                for w in coordinator._workers:
                    w.cancel()
                loop.run_until_complete(
                    asyncio.gather(*coordinator._workers, return_exceptions=True)
                )
            loop.close()


@pytest.mark.asyncio
async def test_submit_propagates_caller_request_id_into_job(make_coordinator):
    """submit() runs on the caller's own task/context, so it can read
    request_id_var directly — but the worker pool's tasks are long-lived and
    were created before this request existed, so nothing propagates there
    automatically. The coordinator must capture the caller's request ID at
    submit() time and apply it for the duration of _run_job so job.fn() (and
    the coordinator's own "IBKR REQUEST" log line) see the right ID."""
    coordinator = make_coordinator(num_workers=1, num_reserved=1)

    seen_id = None

    async def fn():
        nonlocal seen_id
        seen_id = request_id_var.get()
        return "ok"

    token = request_id_var.set("req-abc123")
    try:
        result = await coordinator.submit(Priority.P0, fn)
    finally:
        request_id_var.reset(token)

    assert result == "ok"
    assert seen_id == "req-abc123"
    # The worker's own context must not leak the job's ID into whatever it
    # picks up next — confirmed by checking the caller's context is restored
    # after submit() returns (unaffected either way, but worth pinning).
    assert request_id_var.get() == "-"
