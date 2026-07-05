"""
Closed-bar confirmation & non-repainting rules.

A confirmed signal must be built from COMPLETED candles only. Intrabar signals
are labelled "preliminary" and must never be treated as confirmed. Confirmed
records are immutable — any correction appends a revision, it never overwrites.

This module holds the pure lifecycle logic and the canonical record shape;
persistence lives in models/chart_signal.py. Backtest and live paths both call
build_signal_record() so they cannot diverge.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SignalStatus(str, Enum):
    PRELIMINARY = "preliminary"   # intrabar — not usable for backtest/confirmation
    CONFIRMED = "confirmed"       # built on a closed candle — immutable


@dataclass
class SignalRecord:
    signal_id: str
    symbol: str
    timeframe: str
    candle_open_ts: datetime
    candle_close_ts: datetime
    confirmation_ts: Optional[datetime]
    price_at_confirmation: Optional[float]
    indicator_values: dict
    structure_state: str
    trend_state: str
    volume_state: str
    strategy_version: str
    data_source: str
    data_freshness_s: float
    status: SignalStatus

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_open_ts": self.candle_open_ts.isoformat(),
            "candle_close_ts": self.candle_close_ts.isoformat(),
            "confirmation_ts": self.confirmation_ts.isoformat() if self.confirmation_ts else None,
            "price_at_confirmation": self.price_at_confirmation,
            "indicator_values": self.indicator_values,
            "structure_state": self.structure_state,
            "trend_state": self.trend_state,
            "volume_state": self.volume_state,
            "strategy_version": self.strategy_version,
            "data_source": self.data_source,
            "data_freshness_s": round(self.data_freshness_s, 1),
            "status": self.status.value,
        }


def is_bar_closed(candle_close_ts: datetime, now: datetime | None = None) -> bool:
    """A candle is closed once wall-clock time is at/after its close timestamp."""
    now = now or datetime.now(timezone.utc)
    return now >= candle_close_ts


def build_signal_record(
    *,
    symbol: str,
    timeframe: str,
    candle_open_ts: datetime,
    candle_close_ts: datetime,
    close_price: float,
    indicator_values: dict,
    structure_state: str,
    trend_state: str,
    volume_state: str,
    strategy_version: str,
    data_source: str,
    data_freshness_s: float,
    now: datetime | None = None,
) -> SignalRecord:
    """Build a signal record, stamping preliminary vs confirmed by candle state.

    A deterministic signal_id (symbol|tf|candle_close|strategy_version) makes
    persistence idempotent — the same closed candle never yields a duplicate."""
    now = now or datetime.now(timezone.utc)
    closed = is_bar_closed(candle_close_ts, now)
    status = SignalStatus.CONFIRMED if closed else SignalStatus.PRELIMINARY

    seed = f"{symbol}|{timeframe}|{candle_close_ts.isoformat()}|{strategy_version}"
    signal_id = str(uuid.UUID(hashlib.sha1(seed.encode()).hexdigest()[:32]))

    return SignalRecord(
        signal_id=signal_id,
        symbol=symbol,
        timeframe=timeframe,
        candle_open_ts=candle_open_ts,
        candle_close_ts=candle_close_ts,
        confirmation_ts=now if closed else None,
        price_at_confirmation=close_price if closed else None,
        indicator_values=indicator_values,
        structure_state=structure_state,
        trend_state=trend_state,
        volume_state=volume_state,
        strategy_version=strategy_version,
        data_source=data_source,
        data_freshness_s=data_freshness_s,
        status=status,
    )


@dataclass
class RevisionReason:
    """Why a confirmed signal was revised — appended, never overwriting."""
    reason: str
    changed_fields: list[str] = field(default_factory=list)
    revised_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
