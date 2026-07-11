"""
Execution Mode Manager — Manual / Copilot / Autopilot.

Manual   : Signals generated, NO orders sent. Review in Trade Desk.
Copilot  : Signals queued as pending approvals. User approves → order sent.
Autopilot: Signals pass guardrails → order sent immediately.

Persists across restarts via /tmp/olbostrade_execution_mode.json.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

PERSIST_PATH = "/tmp/olbostrade_exec_mode.json"


class ExecutionMode(str, Enum):
    MANUAL    = "manual"
    COPILOT   = "copilot"
    AUTOPILOT = "autopilot"


class ExecutionModeManager:
    def __init__(self) -> None:
        self._mode = ExecutionMode.MANUAL
        self._changed_at = datetime.now(timezone.utc)
        self._changed_by = "default"
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(open(PERSIST_PATH).read())
            self._mode = ExecutionMode(data.get("mode", "manual"))
            logger.info("ExecutionModeManager restored — mode: %s", self._mode.value.upper())
        except Exception:
            logger.info("ExecutionModeManager initialized — mode: MANUAL (default)")

    def _save(self) -> None:
        try:
            with open(PERSIST_PATH, "w") as f:
                json.dump({"mode": self._mode.value}, f)
        except Exception as e:
            logger.warning("Could not persist execution mode: %s", e)

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def set_mode(self, mode: ExecutionMode, by: str = "user") -> dict:
        prev = self._mode
        self._mode = mode
        self._changed_at = datetime.now(timezone.utc)
        self._changed_by = by
        self._save()
        logger.info("Execution mode: %s → %s (by %s)", prev.value, mode.value, by)
        return self.summary()

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
