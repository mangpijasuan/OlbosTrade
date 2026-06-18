"""
Pause/resume control for the background signal scheduler.

The background scanner in ``main.py`` is a plain asyncio loop, not an
APScheduler instance, so it has no native ``pause()/resume()``. The kill switch
expects a scheduler object exposing those methods; this lightweight singleton
provides them and is polled by the scheduler loop so that engaging the kill
switch actually halts new signal/scan cycles (not just order submission).
"""

from __future__ import annotations

import threading

from app.utils.logger import get_logger

logger = get_logger(__name__)


class SchedulerControl:
    """Thread-safe pause flag shared between the kill switch and the scan loop."""

    def __init__(self) -> None:
        self._paused = threading.Event()

    def pause(self) -> None:
        if not self._paused.is_set():
            self._paused.set()
            logger.info("Scheduler PAUSED — background scan cycles halted")

    def resume(self) -> None:
        if self._paused.is_set():
            self._paused.clear()
            logger.info("Scheduler RESUMED — background scan cycles re-enabled")

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()


# Singleton shared across the app.
scheduler_control = SchedulerControl()
