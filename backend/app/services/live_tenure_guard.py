"""
Live-capital tenure guard — enforces the charter's paper-trading requirement.

The platform charter requires a paper-trading track record before any real
capital is risked ("paper trade for 3 months minimum before any live capital").
Until this module existed that rule lived only in prose: nothing in code stopped
an operator from pointing ``IBKR_TRADING_MODE`` at a real account on day one and
executing immediately. Every other capital-preservation rule here — loss limits,
cooling off, position caps — is enforced in code precisely because a human under
pressure cannot be trusted to self-enforce. This one was the exception.

What it does: when configured for LIVE trading, require a demonstrated track
record — both elapsed time since the first trade and a minimum number of
finished trades — before any order may be submitted. In paper mode it is a
no-op; the gate exists solely to guard the paper → live transition.

Two deliberate limitations, stated rather than hidden:

1. ``trades`` carries no per-row paper/live flag (``trading_mode_at_entry`` is
   the risk style — conservative/balanced/… — not the account type), so this
   measures *all* trading history. Before the first live order that history is
   by definition entirely paper, which is exactly when the gate decides. Once
   live, tenure only grows, so conflating the two afterwards is harmless.
2. Wiping trade history (e.g. ``deploy/hetzner/reset_trading_history.sh``)
   resets the track record and the gate blocks live trading again. That is the
   intended reading: no history, no evidence, no live capital.

Fail-closed: if the track record cannot be read, live execution is blocked,
matching ``account_guard``'s posture. A database blip must never be the reason
real money starts moving.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Trade.status values that count as a finished trade. An open position has not
# taught the operator anything yet — only a closed one has an outcome.
FINISHED_STATUSES = ("closed", "expired")


@dataclass(frozen=True)
class TenureStatus:
    """Result of a tenure check. ``allowed`` False means block live execution."""
    allowed: bool
    reason: Optional[str]
    days_elapsed: Optional[float]
    finished_trades: Optional[int]
    required_days: int
    required_trades: int
    first_trade_at: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "days_elapsed": self.days_elapsed,
            "finished_trades": self.finished_trades,
            "required_days": self.required_days,
            "required_trades": self.required_trades,
            "first_trade_at": self.first_trade_at.isoformat() if self.first_trade_at else None,
        }


async def read_track_record() -> tuple[Optional[datetime], int]:
    """
    Return ``(first_trade_at, finished_trade_count)`` from the trades table.

    ``first_trade_at`` is None when no trade has ever been recorded. Raises on
    database failure — callers fail closed rather than treating an unreadable
    track record as an empty or a sufficient one.
    """
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade

    async with AsyncSessionLocal() as session:
        first_at = (await session.execute(
            select(func.min(Trade.entry_date))
        )).scalar_one_or_none()

        finished = (await session.execute(
            select(func.count()).select_from(Trade)
            .where(Trade.status.in_(FINISHED_STATUSES))
        )).scalar_one_or_none() or 0

    return first_at, int(finished)


async def check_live_tenure() -> TenureStatus:
    """
    Evaluate the paper-trading track record against the configured floors.

    Paper mode and a zero-day requirement both short-circuit to allowed — the
    gate only governs live capital, and setting the requirement to 0 is the
    documented way to switch it off.
    """
    required_days = settings.live_min_paper_trading_days
    required_trades = settings.live_min_paper_closed_trades

    if settings.is_paper_trading:
        return TenureStatus(
            allowed=True, reason="paper_mode", days_elapsed=None, finished_trades=None,
            required_days=required_days, required_trades=required_trades,
        )

    if required_days <= 0 and required_trades <= 0:
        return TenureStatus(
            allowed=True, reason="gate_disabled", days_elapsed=None, finished_trades=None,
            required_days=required_days, required_trades=required_trades,
        )

    first_at, finished = await read_track_record()

    if first_at is None:
        return TenureStatus(
            allowed=False, reason="no_trading_history", days_elapsed=0.0, finished_trades=0,
            required_days=required_days, required_trades=required_trades,
        )

    # Rows written before timezone-aware columns landed can come back naive;
    # treat those as UTC rather than crashing the subtraction below.
    if first_at.tzinfo is None:
        first_at = first_at.replace(tzinfo=timezone.utc)

    days_elapsed = (datetime.now(timezone.utc) - first_at).total_seconds() / 86400.0

    if days_elapsed < required_days:
        return TenureStatus(
            allowed=False, reason="insufficient_paper_days", days_elapsed=days_elapsed,
            finished_trades=finished, required_days=required_days,
            required_trades=required_trades, first_trade_at=first_at,
        )

    if finished < required_trades:
        return TenureStatus(
            allowed=False, reason="insufficient_closed_trades", days_elapsed=days_elapsed,
            finished_trades=finished, required_days=required_days,
            required_trades=required_trades, first_trade_at=first_at,
        )

    return TenureStatus(
        allowed=True, reason=None, days_elapsed=days_elapsed, finished_trades=finished,
        required_days=required_days, required_trades=required_trades, first_trade_at=first_at,
    )


async def verify_live_tenure() -> tuple[bool, str]:
    """
    Guard entry point, mirroring ``account_guard.verify_account_mode``'s
    ``(ok, detail)`` contract so it slots in beside it on the order path.

    ``ok is False`` means execution must be blocked:
      - the paper-trading track record does not yet meet the configured floors, or
      - the track record could not be read (fail closed).
    """
    try:
        status = await check_live_tenure()
    except Exception as exc:
        logger.critical(
            "LIVE TENURE UNVERIFIABLE: could not read the paper-trading track "
            "record (%s). Live execution blocked fail-closed.", exc,
        )
        return False, f"tenure_unverified: {exc}"

    if status.allowed:
        if status.reason == "paper_mode":
            return True, "paper mode — live tenure gate not applicable"
        if status.reason == "gate_disabled":
            return True, "live tenure gate disabled by configuration"
        return True, (
            f"live tenure met: {status.days_elapsed:.0f}d since first trade "
            f"(need {status.required_days}d), {status.finished_trades} finished "
            f"trades (need {status.required_trades})"
        )

    if status.reason == "no_trading_history":
        detail = (
            f"no trading history — {status.required_days}d of paper trading and "
            f"{status.required_trades} finished trades required before live capital"
        )
    elif status.reason == "insufficient_paper_days":
        detail = (
            f"paper tenure {status.days_elapsed:.1f}d of {status.required_days}d "
            f"required before live capital"
        )
    else:
        detail = (
            f"{status.finished_trades} finished trades of {status.required_trades} "
            f"required before live capital ({status.days_elapsed:.0f}d elapsed)"
        )

    logger.critical(
        "LIVE TRADING BLOCKED by tenure gate: %s. The charter requires a paper "
        "track record before real capital; see TRADING_POLICY.md.", detail,
    )
    return False, detail
