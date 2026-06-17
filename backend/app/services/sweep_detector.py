"""
Sweep Detector.

Maintains an in-memory rolling time window per option contract
(ticker, strike, expiry, right) and flags sweeps:

  - sweep  = 3+ prints on the same contract within the window across
             *different* exchanges (an order swept multiple venues).
  - large_sweep = a confirmed sweep whose aggregated premium within the
             window exceeds a configurable threshold (default $500k).

The detector is pure in-memory and thread-unsafe by design — it is driven
from the single asyncio ingest loop. State is bounded: stale windows are
evicted on access and via ``prune()``.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Tuple

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

ContractKey = Tuple[str, float, str, str]  # (ticker, strike, expiry_iso, right)


@dataclass
class _Print:
    ts: float          # monotonic seconds
    exchange: str
    premium: float


@dataclass
class SweepResult:
    sweep_confirmed: bool = False
    large_sweep: bool = False
    distinct_exchanges: int = 0
    window_premium: float = 0.0
    window_prints: int = 0


@dataclass
class SweepDetector:
    """Rolling-window sweep classifier. One instance per ingest service."""

    window_ms: int = field(default_factory=lambda: settings.options_flow_sweep_window_ms)
    large_premium: float = field(
        default_factory=lambda: settings.options_flow_large_sweep_premium
    )
    min_prints: int = 3
    min_exchanges: int = 2

    _windows: Dict[ContractKey, Deque[_Print]] = field(default_factory=dict)

    def record(
        self,
        ticker: str,
        strike: float,
        expiry_iso: str,
        right: str,
        exchange: str,
        premium: float,
        now: float | None = None,
    ) -> SweepResult:
        """Record a print and return the current sweep classification."""
        now = time.monotonic() if now is None else now
        key: ContractKey = (ticker, float(strike), expiry_iso, right)

        window = self._windows.get(key)
        if window is None:
            window = deque()
            self._windows[key] = window

        window.append(_Print(ts=now, exchange=(exchange or "").upper(), premium=premium))

        cutoff = now - (self.window_ms / 1000.0)
        while window and window[0].ts < cutoff:
            window.popleft()

        exchanges = {p.exchange for p in window if p.exchange}
        total_premium = sum(p.premium for p in window)
        n = len(window)

        sweep = n >= self.min_prints and len(exchanges) >= self.min_exchanges
        large = sweep and total_premium >= self.large_premium

        if large:
            logger.info(
                "LARGE SWEEP %s %s%s exp=%s — $%.0f across %d venues (%d prints)",
                ticker, strike, right, expiry_iso, total_premium,
                len(exchanges), n,
            )

        return SweepResult(
            sweep_confirmed=sweep,
            large_sweep=large,
            distinct_exchanges=len(exchanges),
            window_premium=total_premium,
            window_prints=n,
        )

    def prune(self, now: float | None = None) -> None:
        """Drop windows that have had no prints within the active window."""
        now = time.monotonic() if now is None else now
        cutoff = now - (self.window_ms / 1000.0)
        stale = [
            k for k, w in self._windows.items() if not w or w[-1].ts < cutoff
        ]
        for k in stale:
            del self._windows[k]
