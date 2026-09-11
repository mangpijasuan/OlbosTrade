"""
One-off cleanup for the signal_outcomes duplication backlog.

Context: the scanner re-evaluates the whole watchlist every tick, and
`record_signal()` had no guard, so the same setup was re-recorded on every
pass. The 2026-08-28 assessment measured 70,798 rows representing roughly
1,568 real (ticker, action, day) signals — about 45x duplication. That is what
made a ~1,568-signal sample read as 70k, and what blew the resolver's time
budget so it was killed mid-pass every run.

`record_signal()` now keeps one row per (ticker, action, UTC day), so no NEW
duplicates accumulate. This drains the history that built up before that.

Which row survives — deliberately not simply "the earliest":

  1. A row carrying a resolved outcome beats a pending one. Duplicates were
     resolved independently, so the earliest row is often still `pending`
     while a later twin already has a real label. Dropping the labelled twin
     to keep an unlabelled original would destroy exactly the scarce data this
     whole subsystem exists to collect.
  2. Among rows at the same resolution status, the earliest wins — it is the
     moment the setup actually became actionable, before the day's price
     action moved the entry/stop/target under it.

DRY RUN BY DEFAULT. Nothing is deleted without --apply.

Usage:
    python scripts/dedupe_signal_outcomes.py            # measure only
    python scripts/dedupe_signal_outcomes.py --apply    # delete duplicates
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, "/app")

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.signal_outcome import SignalOutcome  # noqa: E402

# A decided label is worth more than a pending one; `expired` sits between
# (a real observation, but not a hit/miss). Higher keeps.
STATUS_RANK = {"target_hit": 3, "stop_hit": 3, "expired": 2, "pending": 1}

DELETE_CHUNK = 500


def keep_rank(row) -> tuple[int, float]:
    """Sort key for choosing the survivor: resolution first, then earliest."""
    status_rank = STATUS_RANK.get(row.status, 0)
    # Negative timestamp so that, at equal status, earlier sorts higher.
    return (status_rank, -row.generated_at.timestamp())


async def main(apply: bool) -> None:
    started = time.time()

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(
                SignalOutcome.id,
                SignalOutcome.ticker,
                SignalOutcome.asset_type,
                SignalOutcome.action,
                SignalOutcome.generated_at,
                SignalOutcome.status,
            )
        )).all()

    print("=" * 70)
    print("SIGNAL OUTCOMES — DUPLICATE CLEANUP")
    print("=" * 70)
    print(f"total rows            : {len(rows):,}")

    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        key = (r.ticker, r.asset_type, r.action, r.generated_at.date())
        groups[key].append(r)

    doomed: list = []
    kept_status = Counter()
    rescued = 0        # groups where the survivor is NOT the earliest row
    for key, members in groups.items():
        if len(members) == 1:
            kept_status[members[0].status] += 1
            continue
        ordered = sorted(members, key=keep_rank, reverse=True)
        survivor, rest = ordered[0], ordered[1:]
        kept_status[survivor.status] += 1
        earliest = min(members, key=lambda r: r.generated_at)
        if survivor.id != earliest.id:
            rescued += 1
        doomed.extend(r.id for r in rest)

    print(f"distinct signal-days  : {len(groups):,}")
    print(f"duplicates to delete  : {len(doomed):,}")
    if rows:
        print(f"duplication factor    : {len(rows)/max(len(groups),1):.1f}x")
    print(f"groups where a resolved twin outranked the earliest row: {rescued:,}")
    print("  ^ these are the labels a naive 'keep the earliest' would have destroyed")
    print("\nsurviving rows by status:")
    for status, n in kept_status.most_common():
        print(f"  {status:12} {n:7,}")

    if not doomed:
        print("\nNothing to do — no duplicates found.")
        return

    if not apply:
        print(f"\nDRY RUN — nothing deleted. Re-run with --apply to remove "
              f"{len(doomed):,} duplicate rows.")
        print("Take a backup first: bash deploy/hetzner/backup_db.sh")
        return

    deleted = 0
    async with AsyncSessionLocal() as session:
        for i in range(0, len(doomed), DELETE_CHUNK):
            chunk = doomed[i:i + DELETE_CHUNK]
            async with session.begin():
                await session.execute(
                    delete(SignalOutcome).where(SignalOutcome.id.in_(chunk))
                )
            deleted += len(chunk)
            print(f"  deleted {deleted:,}/{len(doomed):,}", end="\r", flush=True)

    print(f"\n\nDeleted {deleted:,} duplicate rows in {time.time()-started:.0f}s.")
    print(f"{len(groups):,} distinct signal-days remain.")
    print("\nA UNIQUE index on (ticker, asset_type, action, date(generated_at))")
    print("can now be added safely — it would have failed before this ran.")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
