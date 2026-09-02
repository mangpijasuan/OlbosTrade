"""
Options signal history — persists every qualifying options spread signal.

record_options_signal() is called at signal-generation time (inside the
options scanner, main.py::_run_options_scan) right after the signal is
appended to the in-memory _recent_options_signals store, so it survives a
backend restart the way the in-memory list never does. Mirrors
signal_outcome_tracker.record_signal()'s equity precedent, but options
spreads have no entry/stop/target shape to track a forward outcome
against — this is a signal log only, no resolution logic.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _dec_or_none(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(round(float(value), 4)))
    except (TypeError, ValueError):
        return None


async def record_options_signal(signal: dict) -> Optional[str]:
    """
    Persist a qualifying options spread signal (BUY_SPREAD | SELL_SPREAD)
    for the History view.

    No-ops (returns None) for rejection entries (action other than
    BUY_SPREAD/SELL_SPREAD, or no spread data) — those come from
    _record_options_rejection(), a separate code path with just a reason
    string, nothing to persist. Never raises: a tracking failure must not
    break the scan that produced the signal.
    """
    action = signal.get("action")
    if action not in ("BUY_SPREAD", "SELL_SPREAD"):
        return None

    spread = signal.get("spread") or {}
    if not spread:
        return None

    try:
        from app.core.database import AsyncSessionLocal
        from app.models.options_signal_history import OptionsSignalHistory

        generated_at_raw = signal.get("generated_at")
        try:
            generated_at = (
                datetime.fromisoformat(generated_at_raw)
                if generated_at_raw else datetime.now(timezone.utc)
            )
        except ValueError:
            generated_at = datetime.now(timezone.utc)

        expiration_raw = spread.get("expiration")
        expiration = date.fromisoformat(expiration_raw) if expiration_raw else generated_at.date()

        row_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(OptionsSignalHistory(
                    id=row_id,
                    signal_id=signal.get("id"),
                    ticker=signal.get("ticker", ""),
                    strategy=signal.get("strategy", ""),
                    action=action,
                    confidence=Decimal(str(round(signal.get("confidence", 0.0), 4))),
                    pop=_dec_or_none(signal.get("pop")),
                    kelly_fraction=_dec_or_none(signal.get("kelly_fraction")),
                    signal_score=Decimal(str(round(signal.get("signal_score", 0.0), 4))),
                    quantity=int(signal.get("quantity", 0)),
                    iv_rank=Decimal(str(round(signal.get("iv_rank", 0.0), 2))),
                    regime=signal.get("regime", "unknown"),
                    option_type=spread.get("option_type", ""),
                    short_strike=Decimal(str(spread.get("short_strike", 0))),
                    long_strike=Decimal(str(spread.get("long_strike", 0))),
                    expiration=expiration,
                    dte=int(spread.get("dte", 0)),
                    net_credit=Decimal(str(spread.get("net_credit", 0))),
                    max_loss=Decimal(str(spread.get("max_loss", 0))),
                    breakeven=Decimal(str(spread.get("breakeven", 0))),
                    sigma=Decimal(str(round(signal.get("sigma", 0.0), 4))),
                    vix_used=Decimal(str(round(signal.get("vix_used", 0.0), 2))),
                    credit_source=signal.get("credit_source", "unknown"),
                    evidence=signal.get("evidence"),
                    intelligence=signal.get("intelligence"),
                    generated_at=generated_at,
                ))
        return str(row_id)
    except Exception as exc:
        logger.warning("record_options_signal failed for %s: %s", signal.get("ticker"), exc)
        return None
