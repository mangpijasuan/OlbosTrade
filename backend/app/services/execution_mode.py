"""
Execution Mode Manager — Manual / Copilot / Autopilot.

Manual   : Signals generated, NO orders sent. Review in Trade Desk.
Copilot  : Signals queued as pending approvals. User approves → order sent.
Autopilot: Signals pass guardrails → order sent immediately.

Persisted to the execution_events table (kind="mode_change") so mode survives
a restart. Previously written to /tmp/olbostrade_exec_mode.json inside the
container, wiped on every deploy — the same class of bug as the bracket-order
ack race and pending-order grace-period timer fixed earlier. Mirrors the kill
switch's own DB rehydrate() pattern (kill_switch.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    MANUAL    = "manual"
    COPILOT   = "copilot"
    AUTOPILOT = "autopilot"


class ExecutionModeManager:
    def __init__(self) -> None:
        self._mode = ExecutionMode.MANUAL
        self._changed_at = datetime.now(timezone.utc)
        self._changed_by = "default"

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    async def set_mode(self, mode: ExecutionMode, by: str = "user") -> dict:
        from app.core.database import AsyncSessionLocal
        from app.models.execution_event import ExecutionEvent

        prev = self._mode
        self._mode = mode
        self._changed_at = datetime.now(timezone.utc)
        self._changed_by = by

        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    session.add(ExecutionEvent(
                        kind="mode_change",
                        status=mode.value,
                        payload={
                            "mode": mode.value,
                            "changed_by": by,
                            "changed_at": self._changed_at.isoformat(),
                        },
                    ))
        except Exception as exc:
            logger.error("Could not persist execution mode change: %s", exc)

        logger.info("Execution mode: %s → %s (by %s)", prev.value, mode.value, by)
        return self.summary()

    async def rehydrate(self) -> None:
        """
        Restore the last-set mode from the DB on startup. Defaults to MANUAL
        (the safe default) if there's no history or the read fails.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.execution_event import ExecutionEvent
        from sqlalchemy import select

        try:
            async with AsyncSessionLocal() as session:
                row = (await session.execute(
                    select(ExecutionEvent)
                    .where(ExecutionEvent.kind == "mode_change")
                    .order_by(ExecutionEvent.created_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
            if row is not None:
                self._mode = ExecutionMode(row.status)
                self._changed_at = row.created_at
                self._changed_by = (row.payload or {}).get("changed_by", "restored")
                logger.info(
                    "ExecutionModeManager restored — mode: %s", self._mode.value.upper()
                )
            else:
                logger.info("ExecutionModeManager initialized — mode: MANUAL (default, no history)")
        except Exception as exc:
            logger.error(
                "ExecutionModeManager rehydrate failed (defaulting to MANUAL): %s", exc
            )

    def summary(self) -> dict:
        descriptions = {
            ExecutionMode.MANUAL:    "Signals only — no orders sent. Review in Trade Desk.",
            ExecutionMode.COPILOT:   "Signals queued for your approval. You approve → order executes.",
            ExecutionMode.AUTOPILOT: "Signals auto-execute through guardrails. Kill switch always active.",
        }
        return {
            "mode":        self._mode.value,
            "description": descriptions[self._mode],
            "changed_at":  self._changed_at.isoformat(),
            "changed_by":  self._changed_by,
            "auto_equity":   self._mode == ExecutionMode.AUTOPILOT,
            "auto_options":  self._mode == ExecutionMode.AUTOPILOT,
            "needs_approval": self._mode == ExecutionMode.COPILOT,
        }


# Singleton
execution_mode_manager = ExecutionModeManager()
