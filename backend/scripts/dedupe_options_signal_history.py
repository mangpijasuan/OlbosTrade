"""
One-off cleanup for the options_signal_history duplication backlog.

The options scan ticks every 30 minutes across the watchlist, and
`record_options_signal()` had no guard, so a spread that kept qualifying was
re-recorded on every pass — the same structural bug the equity side had
(measured there at ~45x; this table's slower cadence makes it ~13x per trading
day). `record_options_signal()` now keeps one row per (ticker, strategy,
action, UTC day); this drains the history that built up before that.

Simpler than its equity counterpart: options_signal_history is a signal LOG
with no resolution status, so there is no "a resolved twin outranks an earlier
pending one" case to handle. The earliest row of the day wins outright — it is
the moment the setup first qualified, before the day's spot moved the strikes
under it.

Strikes and expiration are deliberately not part of the identity, matching
record_options_signal(): they drift with spot between ticks, so including them
would dedupe almost nothing.

DRY RUN BY DEFAULT. Nothing is deleted without --apply.

Usage:
    python scripts/dedupe_options_signal_history.py            # measure only
    python scripts/dedupe_options_signal_history.py --apply    # delete duplicates
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, "/app")

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.options_signal_history import OptionsSignalHistory  # noqa: E402

DELETE_CHUNK = 500


async def main(apply: bool) -> None:
    started = time.time()

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(
                OptionsSignalHistory.id,
                OptionsSignalHistory.ticker,
                OptionsSignalHistory.strategy,
                OptionsSignalHistory.action,
                OptionsSignalHistory.generated_at,
            )
        )).all()

    print("=" * 70)
    print("OPTIONS SIGNAL HISTORY — DUPLICATE CLEANUP")
    print("=" * 70)
    print(f"total rows            : {len(rows):,}")

    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r.ticker, r.strategy, r.action, r.generated_at.date())].append(r)

    doomed: list = []
    per_strategy = Counter()
    for members in groups.values():
        survivor, *rest = sorted(members, key=lambda r: r.generated_at)
        per_strategy[survivor.strategy] += 1
        doomed.extend(r.id for r in rest)

    print(f"distinct signal-days  : {len(groups):,}")
    print(f"duplicates to delete  : {len(doomed):,}")
    if groups:
        print(f"duplication factor    : {len(rows)/len(groups):.1f}x")

    if per_strategy:
        print("\nsurviving rows by strategy:")
        for strategy, n in per_strategy.most_common():
            print(f"  {strategy or '(blank)':28} {n:6,}")

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
                    delete(OptionsSignalHistory).where(OptionsSignalHistory.id.in_(chunk))
                )
            deleted += len(chunk)
            print(f"  deleted {deleted:,}/{len(doomed):,}", end="\r", flush=True)

    print(f"\n\nDeleted {deleted:,} duplicate rows in {time.time()-started:.0f}s.")
    print(f"{len(groups):,} distinct signal-days remain.")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
