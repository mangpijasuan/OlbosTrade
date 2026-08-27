"""
Account mode guard — fail-closed protection against trading the wrong account.

OlbosTrade is configured for a trading mode via ``IBKR_TRADING_MODE`` (paper or
live). But the *actual* account the IB Gateway logs into is determined by the
gateway's own credentials/mode, which can drift from our config (e.g. the
gateway is pointed at a LIVE account while we believe we're on paper). IBKR
account numbers encode this:

  - ``DU…`` / ``DF…``  → paper (simulated) account
  - ``U…``             → live (real-money) account

This module compares the broker's real account number against the configured
mode and refuses execution on any mismatch — and, fail-closed, when the account
can't be verified at all. The goal is simple: never place a real-money order
when the operator believes they're on paper.
"""

from __future__ import annotations

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ibkr_coordinator's own default (30s) is too slow here: this check runs on
# every execution attempt (trade_desk.py's gate stages), so a degraded
# connection would add up to 30s to every single trade attempt. Fail closed
# faster instead — the fail-closed *behavior* on timeout is unchanged and
# correct; only how long it takes to reach that verdict shrinks.
ACCOUNT_SUMMARY_TIMEOUT_SECONDS = 5.0


def account_is_paper(account_id: str | None) -> bool:
    """True if the IBKR account number is a paper (simulated) account.

    Paper accounts are prefixed ``DU`` (individual) or ``DF`` (paper FA). Any
    other non-empty value — notably a ``U…`` prefix — is treated as live.
    """
    aid = (account_id or "").upper().strip()
    return aid.startswith("DU") or aid.startswith("DF")


def configured_paper() -> bool:
    """True if OlbosTrade is configured to trade paper (not live)."""
    return settings.ibkr_trading_mode.lower() != "live"


async def verify_account_mode(broker) -> tuple[bool, str]:
    """
    Verify the broker's real account matches the configured trading mode.

    Returns ``(ok, detail)``. ``ok is False`` means execution must be blocked:
      - a positive paper/live mismatch (the dangerous case), or
      - the account could not be determined (fail-closed — we never assume safe).
    """
    try:
        from app.broker.ibkr_coordinator import Priority, ibkr_coordinator
        acct = await ibkr_coordinator.submit(
            Priority.P0, broker.get_account_summary,
            key="account_summary", req_type="ACCOUNT_SUMMARY", timeout=ACCOUNT_SUMMARY_TIMEOUT_SECONDS,
        )
        account_id = (acct.account_id or "").strip()
    except Exception as exc:
        return False, f"account_unverified: {exc}"

    if not account_id or account_id.lower() == "unknown":
        return False, "account_unverified: broker returned no account id"

    actual_paper = account_is_paper(account_id)
    want_paper = configured_paper()

    if want_paper and not actual_paper:
        logger.critical(
            "ACCOUNT MODE MISMATCH: IBKR_TRADING_MODE=paper but broker account "
            "%s is LIVE (real money). Execution blocked fail-closed.", account_id,
        )
        return False, f"mode_mismatch: configured paper but account {account_id} is LIVE"

    if not want_paper and actual_paper:
        logger.critical(
            "ACCOUNT MODE MISMATCH: IBKR_TRADING_MODE=live but broker account "
            "%s is PAPER. Execution blocked fail-closed.", account_id,
        )
        return False, f"mode_mismatch: configured live but account {account_id} is PAPER"

    return True, f"account {account_id} ({'paper' if actual_paper else 'live'})"
