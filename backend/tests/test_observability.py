"""Tests for the lightweight in-process observability registry."""

from __future__ import annotations

from app.services.observability import Observability, observability


def test_counters_increment():
    o = Observability()
    o.incr("a")
    o.incr("a", 4)
    o.incr("b")
    assert o.counter("a") == 5
    assert o.counter("b") == 1
    assert o.counter("missing") == 0


def test_gauges_set_and_overwrite():
    o = Observability()
    o.gauge("g", 1.0)
    o.gauge("g", 2.5)
    assert o.snapshot()["gauges"]["g"] == 2.5


def test_events_ring_buffer_caps_size():
    o = Observability(ring_size=3)
    for i in range(5):
        o.event("tick", i=i)
    recent = o.recent()
    assert len(recent) == 3                # only last 3 retained
    assert recent[0]["i"] == 4             # newest first


def test_recent_filters_by_name():
    o = Observability()
    o.event("blocked", reason="x")
    o.event("submitted", ticker="SPY")
    o.event("blocked", reason="y")
    blocked = o.recent(name="blocked")
    assert len(blocked) == 2
    assert all(e["name"] == "blocked" for e in blocked)


def test_recent_limit():
    o = Observability()
    for i in range(10):
        o.event("e", i=i)
    assert len(o.recent(limit=4)) == 4


def test_event_records_timestamp_and_fields():
    o = Observability()
    o.event("submitted", ticker="AAPL", order_id="ORD-1")
    e = o.recent()[0]
    assert e["name"] == "submitted" and e["ticker"] == "AAPL"
    assert e["order_id"] == "ORD-1" and isinstance(e["ts"], float)


def test_snapshot_shape():
    o = Observability()
    o.incr("execute.attempt", 3)
    o.gauge("scanner.last_tick", 12.0)
    o.event("blocked", reason="kill_switch")
    snap = o.snapshot()
    assert snap["counters"]["execute.attempt"] == 3
    assert snap["gauges"]["scanner.last_tick"] == 12.0
    assert snap["event_count"] == 1
    assert snap["recent_events"][0]["name"] == "blocked"
    assert snap["uptime_seconds"] >= 0


def test_snapshot_respects_recent_limit():
    o = Observability()
    for i in range(30):
        o.event("e", i=i)
    snap = o.snapshot(recent_limit=5)
    assert len(snap["recent_events"]) == 5


def test_reset_clears_everything():
    o = Observability()
    o.incr("a")
    o.gauge("g", 1.0)
    o.event("e")
    o.reset()
    snap = o.snapshot()
    assert snap["counters"] == {} and snap["gauges"] == {}
    assert snap["recent_events"] == []
    assert o.counter("a") == 0


def test_module_singleton_exists():
    assert isinstance(observability, Observability)
