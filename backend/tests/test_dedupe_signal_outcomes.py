"""
Tests for the duplicate-cleanup script's survivor selection.

This logic decides which signal_outcomes rows get deleted from production, so
the rule it encodes — a resolved row outranks a pending one, and the earliest
wins among equals — is worth pinning down rather than trusting by inspection.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dedupe_signal_outcomes import keep_rank  # noqa: E402

BASE = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


def _row(status: str, minutes: int = 0, rid: str = "r"):
    return SimpleNamespace(id=rid, status=status, generated_at=BASE + timedelta(minutes=minutes))


def _survivor(*rows):
    return sorted(rows, key=keep_rank, reverse=True)[0]


def test_resolved_row_beats_an_earlier_pending_one():
    """The whole point: never drop a real label to keep an unlabelled original."""
    earliest_pending = _row("pending", 0, "pending-first")
    later_resolved = _row("target_hit", 90, "resolved-later")
    assert _survivor(earliest_pending, later_resolved).id == "resolved-later"


def test_stop_hit_ranks_equal_to_target_hit():
    """Both are decided outcomes — neither is more informative than the other."""
    first_stop = _row("stop_hit", 0, "stop-first")
    later_target = _row("target_hit", 90, "target-later")
    # Equal status rank, so the earlier row wins on the tiebreak.
    assert _survivor(first_stop, later_target).id == "stop-first"


def test_expired_beats_pending_but_loses_to_decided():
    expired = _row("expired", 60, "expired")
    pending = _row("pending", 0, "pending")
    decided = _row("stop_hit", 120, "decided")
    assert _survivor(expired, pending).id == "expired"
    assert _survivor(expired, decided).id == "decided"


def test_earliest_wins_among_rows_of_the_same_status():
    """Within a status, the first emission is the actionable moment."""
    first = _row("pending", 0, "first")
    middle = _row("pending", 30, "middle")
    last = _row("pending", 300, "last")
    assert _survivor(last, middle, first).id == "first"


def test_unknown_status_ranks_below_everything_known():
    """An unrecognised status must not silently outrank a real label."""
    weird = _row("something_new", 0, "weird")
    pending = _row("pending", 90, "pending")
    assert _survivor(weird, pending).id == "pending"
