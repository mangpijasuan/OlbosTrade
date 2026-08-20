"""
Trade identity helpers — equity vs options must not share one key.

Used by the OMS duplicate guard and paper-trade positions merge so holding
SPY shares and a SPY option spread at once does not clobber or false-block.
"""

from __future__ import annotations

from typing import Any, Optional


def asset_class_from_trade(trade: Any) -> str:
    """Return 'equity' or 'options' from a Trade row (or duck-typed mock)."""
    st = (getattr(trade, "spread_type", None) or "").lower()
    strat = (getattr(trade, "strategy", None) or "").lower()
    if st.startswith("equity") or strat == "equity":
        return "equity"
    return "options"


def asset_class_from_signal(signal: dict) -> str:
    """Return 'equity' or 'options' from an OMS / queue signal dict."""
    raw = (signal.get("asset_type") or "").lower().strip()
    if raw in ("equity", "stock", "shares"):
        return "equity"
    if raw in ("options", "option"):
        return "options"
    strat = (signal.get("strategy") or "").lower()
    if strat == "equity" or strat.startswith("equity_"):
        return "equity"
    if signal.get("spread") or strat:
        return "options"
    return "equity"


def position_identity_key(underlying: str, asset_class: str) -> tuple[str, str]:
    return ((underlying or "").upper(), "equity" if asset_class == "equity" else "options")
