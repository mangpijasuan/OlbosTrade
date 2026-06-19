"""
MODULE 4 — Safety-First Risk Manager Extension & Execution Dispatcher.

This is an EXTENSION of risk_manager.py, not a replacement.

risk_manager.py (existing):       Portfolio-level guards (Greeks limits,
                                  concentration, position sizing).
ExecutionDispatcher (here):       Order-level guards + atomic fill simulation
                                  + flatten-and-cancel recovery logic.

The two classes work in sequence:
    GuardrailEngine.check_all()         → portfolio psychology limits
    RiskManager.approve_trade()         → portfolio Greeks/concentration limits
    ExecutionDispatcher.validate()      → order-level liquidity + spread guards
    ExecutionDispatcher.submit_atomic() → atomic fill with flatten fallback

The key additions in this module that do NOT exist elsewhere in OlbosQuant:
  1. Per-leg bid-ask spread width guard (MAX_SPREAD_PCT)
  2. Atomic fill simulation with per-leg timeout
  3. Flatten-and-cancel recovery for partial fills
  4. Full async event loop with threading.Event for fill signals
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Literal, Optional

from app.broker.broker_interface import BrokerInterface, OrderResult, SpreadOrder
from app.broker.contract import EnrichedContract
from app.services.multi_leg_strategy import LegAction, MultiLegStrategy, StrategyLeg
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

# Default max spread as % of mid before rejecting a leg as illiquid
DEFAULT_MAX_SPREAD_PCT = 15.0

# Per-leg fill timeout in seconds before triggering flatten-and-cancel
DEFAULT_LEG_TIMEOUT_SECONDS = 30.0

# Max time to wait for flatten orders to complete before giving up
FLATTEN_TIMEOUT_SECONDS = 60.0


# ── Enums and result types ────────────────────────────────────────────────────

class ValidationStatus(str, Enum):
    APPROVED  = "approved"
    REJECTED  = "rejected"
    WARNED    = "warned"


class DispatchStatus(str, Enum):
    FILLED           = "filled"
    PARTIAL_FLATTENED = "partial_flattened"   # partial fill → flatten ran
    TIMEOUT_FLATTENED = "timeout_flattened"   # timeout → flatten ran
    REJECTED         = "rejected"             # never submitted
    FLATTEN_FAILED   = "flatten_failed"       # flatten itself failed — CRITICAL


@dataclass
class LegValidation:
    """Validation result for a single leg."""
    leg:          StrategyLeg
    status:       ValidationStatus
    spread_pct:   float
    reason:       Optional[str] = None


@dataclass
class OrderValidation:
    """Aggregate validation result for all legs."""
    status:        ValidationStatus
    leg_results:   list[LegValidation]
    blocking_legs: list[LegValidation]     # legs that caused REJECTED status
    warned_legs:   list[LegValidation]     # legs with high but not blocking spread
    reason:        Optional[str] = None

    @property
    def approved(self) -> bool:
        return self.status in (ValidationStatus.APPROVED, ValidationStatus.WARNED)


@dataclass
class LegFillEvent:
    """Represents a fill event for a single leg."""
    leg_index:   int
    symbol:      str
    fill_price:  float
    filled_at:   datetime
    order_id:    str


@dataclass
class FlattenResult:
    """Result of a flatten-and-cancel operation."""
    triggered_reason: str
    legs_flattened:   int
    legs_failed:      list[str]
    flatten_pnl:      float      # net P&L from entry fills vs flatten fills
    completed_at:     datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class DispatchResult:
    """
    Full result of an atomic order dispatch attempt.
    Always check status before assuming fills are clean.
    """
    order_id:     str
    status:       DispatchStatus
    strategy:     str
    underlying:   str
    fills:        list[LegFillEvent]
    flatten:      Optional[FlattenResult] = None
    net_fill_price: Optional[float] = None
    error:        Optional[str] = None
    elapsed_ms:   float = 0.0


class ExecutionDispatcher:
    """
    Safety-first execution layer with three responsibilities:

    1. LIQUIDITY VALIDATION
       Reject any leg whose bid-ask spread exceeds MAX_SPREAD_PCT of its
       mid-price. Illiquid fills are the #1 way retail traders lose money
       before the trade even starts.

    2. ATOMIC FILL SIMULATION / SUBMISSION
       Simulate an event-driven fill loop: submit each leg and wait for
       fill confirmation within a timeout window. If any leg times out,
       trigger flatten-and-cancel on already-filled legs.

    3. FLATTEN-AND-CANCEL RECOVERY
       If a partial fill occurs (some legs filled, others didn't), immediately
       market-order out of the filled legs to eliminate naked residual risk.
       This is the most critical safety mechanism for multi-leg orders.

    Thread safety:
       Uses asyncio for the fill event loop. Threading.Event for fill
       signal communication. All shared state is protected by asyncio locks.
    """

    def __init__(
        self,
        broker: BrokerInterface,
        max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT,
        leg_timeout_seconds: float = DEFAULT_LEG_TIMEOUT_SECONDS,
        warn_spread_pct: float = 8.0,
    ) -> None:
        self.broker = broker
        self.max_spread_pct    = max_spread_pct
        self.leg_timeout       = leg_timeout_seconds
        self.warn_spread_pct   = warn_spread_pct
        self._lock = asyncio.Lock()
        self._inflight: set[str] = set()   # client_order_ids currently dispatching

        logger.info(
            "ExecutionDispatcher initialized — "
            "max_spread_pct=%.1f%% leg_timeout=%.1fs",
            max_spread_pct, leg_timeout_seconds,
        )

    # ── Module 4a: Spread Width Guard ─────────────────────────────────────────

    def validate_liquidity(self, strategy: MultiLegStrategy) -> OrderValidation:
        """
        Validate all legs against the spread width guard.

        Rejects the order if ANY leg's bid-ask spread exceeds max_spread_pct
        of that leg's mid price. This prevents fills at horrible illiquid prices.

        Also warns on legs above warn_spread_pct but below max_spread_pct.

        Args:
            strategy: The MultiLegStrategy to validate

        Returns:
            OrderValidation — check .approved before submitting
        """
        leg_results: list[LegValidation] = []

        for leg in strategy.legs:
            contract = leg.contract
            spread_pct = contract.spread_pct

            if spread_pct == float("inf"):
                # Mid price is zero — completely untradeable
                result = LegValidation(
                    leg=leg,
                    status=ValidationStatus.REJECTED,
                    spread_pct=spread_pct,
                    reason=(
                        f"Mid price is zero for {contract!r} — "
                        f"no market maker quote available"
                    ),
                )
            elif spread_pct > self.max_spread_pct:
                result = LegValidation(
                    leg=leg,
                    status=ValidationStatus.REJECTED,
                    spread_pct=spread_pct,
                    reason=(
                        f"Spread {spread_pct:.1f}% exceeds max "
                        f"{self.max_spread_pct:.1f}% for {contract!r}. "
                        f"Bid={contract.bid:.3f} Ask={contract.ask:.3f} "
                        f"Mid={contract.mid_price:.3f}. "
                        f"This leg is too illiquid to fill at a fair price."
                    ),
                )
            elif spread_pct > self.warn_spread_pct:
                result = LegValidation(
                    leg=leg,
                    status=ValidationStatus.WARNED,
                    spread_pct=spread_pct,
                    reason=(
                        f"Spread {spread_pct:.1f}% is elevated "
                        f"(warn threshold: {self.warn_spread_pct:.1f}%). "
                        f"Fill quality may be poor."
                    ),
                )
            else:
                result = LegValidation(
                    leg=leg,
                    status=ValidationStatus.APPROVED,
                    spread_pct=spread_pct,
                )

            leg_results.append(result)

            if result.status == ValidationStatus.REJECTED:
                logger.warning(
                    "LIQUIDITY REJECT: %s", result.reason
                )
            elif result.status == ValidationStatus.WARNED:
                logger.warning(
                    "LIQUIDITY WARN: %s", result.reason
                )

        blocking = [r for r in leg_results if r.status == ValidationStatus.REJECTED]
        warned   = [r for r in leg_results if r.status == ValidationStatus.WARNED]

        if blocking:
            status = ValidationStatus.REJECTED
            reason = (
                f"{len(blocking)} leg(s) failed liquidity check: "
                + "; ".join(r.reason for r in blocking if r.reason)
            )
        elif warned:
            status = ValidationStatus.WARNED
            reason = f"{len(warned)} leg(s) have elevated spread — proceeding with caution"
        else:
            status = ValidationStatus.APPROVED
            reason = None

        validation = OrderValidation(
            status=status,
            leg_results=leg_results,
            blocking_legs=blocking,
            warned_legs=warned,
            reason=reason,
        )

        logger.info(
            "Liquidity validation: %s | %d legs | %d blocking | %d warned",
            status.value, len(leg_results), len(blocking), len(warned),
        )
        return validation

    # ── Module 4b: Atomic Fill Simulation ────────────────────────────────────

    async def submit_atomic(
        self,
        strategy: MultiLegStrategy,
        dry_run: bool = False,
    ) -> DispatchResult:
        """
        Submit a multi-leg order atomically with timeout and flatten fallback.

        Algorithm:
          1. Validate liquidity — reject if any leg fails spread guard
          2. Submit each leg as a separate order with a timeout
          3. If all legs fill within timeout: return FILLED
          4. If any leg times out: trigger flatten-and-cancel on filled legs
          5. Log all events for post-trade analysis

        Args:
            strategy:  MultiLegStrategy to submit
            dry_run:   If True, simulates fills without hitting broker API
                       (used for paper trading simulation mode)

        Returns:
            DispatchResult — always check .status
        """
        start_time = time.monotonic()
        dispatch_id = str(uuid.uuid4())

        logger.info(
            "Atomic dispatch starting: %r | dispatch_id=%s dry_run=%s",
            strategy, dispatch_id, dry_run,
        )

        # ── Step 1: Liquidity validation ──────────────────────────────────────
        validation = self.validate_liquidity(strategy)
        if not validation.approved and validation.status == ValidationStatus.REJECTED:
            return DispatchResult(
                order_id=dispatch_id,
                status=DispatchStatus.REJECTED,
                strategy=strategy.strategy_name,
                underlying=strategy.underlying,
                fills=[],
                error=validation.reason,
                elapsed_ms=(time.monotonic() - start_time) * 1000,
            )

        # ── Real orders: submit ONE native combo (atomic, no legging risk) ────
        # Per-leg submission can leave a filled short leg with an unfilled long
        # (naked exposure). For live/paper-broker orders we send a single combo
        # via broker.place_order, which fills all-or-none. The per-leg path below
        # is kept ONLY for dry_run simulation (no real orders placed there).
        if not dry_run:
            return await self._submit_combo(strategy, dispatch_id, start_time)

        # ── Step 2: Submit legs and await fills (dry_run simulation only) ─────
        fills: list[LegFillEvent] = []
        timed_out_legs: list[StrategyLeg] = []

        # Lock is acquired only to record fills, NOT during network I/O.
        # Holding the lock across blocking broker calls would freeze concurrent dispatches.
        for i, leg in enumerate(strategy.legs):
            try:
                fill_event = await self._submit_leg_with_timeout(
                    leg=leg,
                    leg_index=i,
                    dispatch_id=dispatch_id,
                    dry_run=dry_run,
                )
                async with self._lock:
                    fills.append(fill_event)
                logger.info(
                    "Leg %d/%d filled: %r at $%.4f",
                    i + 1, len(strategy.legs), leg, fill_event.fill_price,
                )

            except asyncio.TimeoutError:
                timed_out_legs.append(leg)
                logger.error(
                    "LEG TIMEOUT: leg %d/%d (%r) did not fill within %.1fs. "
                    "Triggering flatten-and-cancel on %d filled legs.",
                    i + 1, len(strategy.legs), leg, self.leg_timeout, len(fills),
                )
                break  # Stop submitting further legs immediately

            except Exception as exc:
                timed_out_legs.append(leg)
                logger.error(
                    "LEG SUBMISSION ERROR: leg %d/%d (%r): %s. "
                    "Triggering flatten-and-cancel.",
                    i + 1, len(strategy.legs), leg, exc,
                )
                break

        # ── Step 3: All legs filled cleanly ───────────────────────────────────
        if not timed_out_legs:
            net_fill = sum(
                f.fill_price * (1 if strategy.legs[f.leg_index].action == LegAction.SELL else -1)
                for f in fills
            )
            elapsed = (time.monotonic() - start_time) * 1000
            logger.info(
                "Atomic fill SUCCESS: %s %s | net_fill=%.4f | %.1fms",
                strategy.strategy_name, strategy.underlying, net_fill, elapsed,
            )
            return DispatchResult(
                order_id=dispatch_id,
                status=DispatchStatus.FILLED,
                strategy=strategy.strategy_name,
                underlying=strategy.underlying,
                fills=fills,
                net_fill_price=net_fill,
                elapsed_ms=elapsed,
            )

        # ── Step 4: Partial fill — flatten-and-cancel ──────────────────────────
        logger.critical(
            "PARTIAL FILL DETECTED: %d/%d legs filled. "
            "Executing flatten-and-cancel to eliminate naked exposure.",
            len(fills), len(strategy.legs),
        )

        flatten_result = await self._flatten_and_cancel(
            filled_legs=[(strategy.legs[f.leg_index], f) for f in fills],
            strategy=strategy,
            dispatch_id=dispatch_id,
            dry_run=dry_run,
        )

        final_status = (
            DispatchStatus.FLATTEN_FAILED
            if flatten_result.legs_failed
            else (
                DispatchStatus.TIMEOUT_FLATTENED
                if timed_out_legs else DispatchStatus.PARTIAL_FLATTENED
            )
        )

        elapsed = (time.monotonic() - start_time) * 1000
        return DispatchResult(
            order_id=dispatch_id,
            status=final_status,
            strategy=strategy.strategy_name,
            underlying=strategy.underlying,
            fills=fills,
            flatten=flatten_result,
            elapsed_ms=elapsed,
            error=(
                f"Flatten completed with errors: {flatten_result.legs_failed}"
                if flatten_result.legs_failed else None
            ),
        )

    async def _submit_combo(
        self,
        strategy: MultiLegStrategy,
        dispatch_id: str,
        start_time: float,
    ) -> DispatchResult:
        """
        Submit the strategy as a SINGLE native combo order (all-or-none).
        Eliminates the partial-fill / naked-exposure window of per-leg submission.
        """
        order = strategy.to_spread_order()
        try:
            result = await self.broker.place_order(order)
        except Exception as exc:
            logger.error("Combo submission error for %r: %s", strategy, exc)
            return DispatchResult(
                order_id=dispatch_id, status=DispatchStatus.REJECTED,
                strategy=strategy.strategy_name, underlying=strategy.underlying,
                fills=[], error=str(exc),
                elapsed_ms=(time.monotonic() - start_time) * 1000,
            )

        elapsed = (time.monotonic() - start_time) * 1000
        if str(getattr(result, "status", "")) == "filled":
            net = float(result.fill_price) if result.fill_price is not None else None
            fills = [LegFillEvent(
                leg_index=i, symbol=leg.contract.underlying_ticker,
                fill_price=net if net is not None else leg.contract.mid_price,
                filled_at=datetime.now(timezone.utc),
                order_id=str(result.order_id),
            ) for i, leg in enumerate(strategy.legs)]
            logger.info(
                "Combo FILLED: %s %s net=%s order_id=%s %.1fms",
                strategy.strategy_name, strategy.underlying, net, result.order_id, elapsed,
            )
            return DispatchResult(
                order_id=str(result.order_id), status=DispatchStatus.FILLED,
                strategy=strategy.strategy_name, underlying=strategy.underlying,
                fills=fills, net_fill_price=net, elapsed_ms=elapsed,
            )

        # Not filled — combo is all-or-none, so nothing is open; no flatten needed.
        logger.warning(
            "Combo NOT filled (%s) for %s %s — no naked exposure (all-or-none)",
            getattr(result, "status", "?"), strategy.strategy_name, strategy.underlying,
        )
        return DispatchResult(
            order_id=str(getattr(result, "order_id", dispatch_id)),
            status=DispatchStatus.REJECTED,
            strategy=strategy.strategy_name, underlying=strategy.underlying,
            fills=[], error=getattr(result, "message", None) or str(getattr(result, "status", "not_filled")),
            elapsed_ms=elapsed,
        )

    async def _submit_leg_with_timeout(
        self,
        leg: StrategyLeg,
        leg_index: int,
        dispatch_id: str,
        dry_run: bool,
    ) -> LegFillEvent:
        """
        Submit a single leg and wait for fill within timeout.

        In dry_run mode: simulates an instant fill at mid price.
        In live mode: submits to broker and polls for fill status.

        Raises asyncio.TimeoutError if fill doesn't arrive within self.leg_timeout.
        """
        contract = leg.contract

        if dry_run:
            # Simulate realistic fill delay (50-500ms)
            contract_key = getattr(contract, "symbol", None) or getattr(contract, "underlying_ticker", str(id(contract)))
            await asyncio.sleep(0.05 + (hash(contract_key) % 10) * 0.05)
            fill_price = contract.mid_price
            order_id   = f"SIM-{dispatch_id[:8]}-{leg_index}"
        else:
            # Live submission via broker interface
            from decimal import Decimal
            from app.broker.broker_interface import SpreadLeg, SpreadOrder

            leg_order = SpreadOrder(
                strategy=f"single_leg_{leg_index}",
                underlying=contract.underlying_ticker,
                legs=[SpreadLeg(
                    symbol=contract.underlying_ticker,
                    strike=Decimal(str(contract.strike_price)),
                    expiration=contract.expiration_date,
                    option_type=contract.option_type,
                    action=leg.action.value,
                    quantity=leg.quantity,
                )],
                limit_price=Decimal(str(contract.mid_price)),
                order_type="LMT",
                time_in_force="DAY",
                client_order_id=f"{dispatch_id}-{leg_index}",
            )

            result: OrderResult = await asyncio.wait_for(
                self.broker.place_order(leg_order),
                timeout=self.leg_timeout,
            )

            if result.status in ("rejected", "cancelled"):
                raise RuntimeError(
                    f"Leg {leg_index} rejected by broker: {result.message}"
                )

            fill_price = float(result.fill_price) if result.fill_price else contract.mid_price
            order_id   = result.order_id

        return LegFillEvent(
            leg_index=leg_index,
            symbol=contract.underlying_ticker,
            fill_price=fill_price,
            filled_at=datetime.now(timezone.utc),
            order_id=order_id,
        )

    # ── Module 4c: Flatten-and-Cancel ─────────────────────────────────────────

    async def _flatten_and_cancel(
        self,
        filled_legs: list[tuple[StrategyLeg, LegFillEvent]],
        strategy: MultiLegStrategy,
        dispatch_id: str,
        dry_run: bool,
    ) -> FlattenResult:
        """
        Flatten-and-cancel recovery for partial fills.

        For each filled leg, submit a market order in the opposite direction
        to eliminate residual naked exposure.

        This MUST complete — we use MKT orders and do not impose a tight
        timeout here (we use FLATTEN_TIMEOUT_SECONDS instead, which is
        intentionally generous to ensure fills go through).

        Args:
            filled_legs: Tuples of (StrategyLeg, LegFillEvent) that need unwinding
            strategy:    Original strategy (for context logging)
            dispatch_id: Original dispatch ID for audit trail
            dry_run:     If True, simulate flatten without hitting broker

        Returns:
            FlattenResult with details of what was flattened and the net P&L impact
        """
        if not filled_legs:
            return FlattenResult(
                triggered_reason="no_filled_legs",
                legs_flattened=0,
                legs_failed=[],
                flatten_pnl=0.0,
            )

        logger.critical(
            "FLATTEN-AND-CANCEL executing: unwinding %d filled leg(s) "
            "for dispatch_id=%s strategy=%s",
            len(filled_legs), dispatch_id, strategy.strategy_name,
        )

        legs_flattened = 0
        legs_failed: list[str] = []
        flatten_pnl = 0.0

        flatten_tasks = [
            self._flatten_single_leg(leg, fill_event, dispatch_id, dry_run, i)
            for i, (leg, fill_event) in enumerate(filled_legs)
        ]

        # Run all flatten orders concurrently with a global timeout
        try:
            flatten_outcomes = await asyncio.wait_for(
                asyncio.gather(*flatten_tasks, return_exceptions=True),
                timeout=FLATTEN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.critical(
                "FLATTEN TIMED OUT after %.1fs — MANUAL INTERVENTION REQUIRED "
                "for dispatch_id=%s. Check broker for unhedged positions.",
                FLATTEN_TIMEOUT_SECONDS, dispatch_id,
            )
            return FlattenResult(
                triggered_reason="flatten_global_timeout",
                legs_flattened=legs_flattened,
                legs_failed=[f"global_timeout after {FLATTEN_TIMEOUT_SECONDS}s"],
                flatten_pnl=flatten_pnl,
            )

        for i, outcome in enumerate(flatten_outcomes):
            leg, fill_event = filled_legs[i]
            if isinstance(outcome, Exception):
                error_msg = f"leg_{i}_{leg.contract.underlying_ticker}: {outcome}"
                legs_failed.append(error_msg)
                logger.critical(
                    "FLATTEN FAILED for leg %d (%r): %s — NAKED POSITION REMAINS",
                    i, leg, outcome,
                )
            else:
                flatten_fill_price, entry_fill_price = outcome
                legs_flattened += 1
                # P&L = what we got on entry - what we paid to exit (for SELL legs)
                if leg.action == LegAction.SELL:
                    flatten_pnl += (entry_fill_price - flatten_fill_price) * leg.quantity * 100
                else:
                    flatten_pnl += (flatten_fill_price - entry_fill_price) * leg.quantity * 100

        if legs_failed:
            logger.critical(
                "CRITICAL: %d flatten orders FAILED. Naked positions may exist. "
                "Failed legs: %s. Immediate manual intervention required.",
                len(legs_failed), legs_failed,
            )
        else:
            logger.info(
                "Flatten complete: %d legs unwound, flatten P&L = $%.2f",
                legs_flattened, flatten_pnl,
            )

        return FlattenResult(
            triggered_reason="partial_fill_unwind",
            legs_flattened=legs_flattened,
            legs_failed=legs_failed,
            flatten_pnl=flatten_pnl,
        )

    async def _flatten_single_leg(
        self,
        leg: StrategyLeg,
        fill_event: LegFillEvent,
        dispatch_id: str,
        dry_run: bool,
        flatten_index: int,
    ) -> tuple[float, float]:
        """
        Submit a market order to flatten one previously filled leg.

        Returns (flatten_fill_price, entry_fill_price) for P&L calculation.
        Raises on failure — caller handles via asyncio.gather(return_exceptions=True).
        """
        contract = leg.contract
        # Reverse the action: if we SOLD, now BUY to close; if we BOUGHT, now SELL
        reverse_action = "BUY" if leg.action == LegAction.SELL else "SELL"

        logger.warning(
            "Flattening leg %d: %s %d %r at MKT (was filled at %.4f)",
            flatten_index, reverse_action, leg.quantity, contract,
            fill_event.fill_price,
        )

        if dry_run:
            await asyncio.sleep(0.02)  # Simulate execution latency
            # Simulate some adverse slippage on the flatten (realistic)
            slippage = contract.spread_width * 0.30
            flatten_price = (
                contract.ask + slippage
                if reverse_action == "BUY"
                else contract.bid - slippage
            )
            return flatten_price, fill_event.fill_price

        # Live flatten via broker
        from decimal import Decimal
        from app.broker.broker_interface import SpreadLeg, SpreadOrder

        flatten_order = SpreadOrder(
            strategy=f"flatten_{dispatch_id[:8]}_{flatten_index}",
            underlying=contract.underlying_ticker,
            legs=[SpreadLeg(
                symbol=contract.underlying_ticker,
                strike=Decimal(str(contract.strike_price)),
                expiration=contract.expiration_date,
                option_type=contract.option_type,
                action=reverse_action,
                quantity=leg.quantity,
            )],
            limit_price=Decimal("0"),
            order_type="MKT",  # Market order — fill at any price
            time_in_force="DAY",
            client_order_id=f"FLATTEN-{dispatch_id}-{flatten_index}",
        )

        result: OrderResult = await self.broker.place_order(flatten_order)
        if result.status in ("rejected",):
            raise RuntimeError(
                f"Flatten order rejected by broker: {result.message}. "
                f"NAKED POSITION REMAINS for {contract!r}"
            )

        flatten_price = float(result.fill_price) if result.fill_price else contract.mid_price
        return flatten_price, fill_event.fill_price

    # ── Convenience: full pipeline ─────────────────────────────────────────────

    async def validate_and_dispatch(
        self,
        strategy: MultiLegStrategy,
        dry_run: bool = False,
    ) -> DispatchResult:
        """
        Full pipeline: validate liquidity → submit atomically.
        This is the single entry point for order submission.

        Returns DispatchResult — always check .status.
        FILLED = success, everything else = investigate immediately.
        """
        validation = self.validate_liquidity(strategy)

        if not validation.approved and validation.status == ValidationStatus.REJECTED:
            logger.warning(
                "Order REJECTED before submission: %s", validation.reason
            )
            return DispatchResult(
                order_id=str(uuid.uuid4()),
                status=DispatchStatus.REJECTED,
                strategy=strategy.strategy_name,
                underlying=strategy.underlying,
                fills=[],
                error=validation.reason,
            )

        # Idempotency guard: refuse a duplicate dispatch of the same order while
        # one is already in flight (prevents double submission from concurrent
        # callers). Full cross-restart dedupe (dispatch_id UNIQUE) is batch 4.
        key = strategy.order_id
        async with self._lock:
            if key in self._inflight:
                logger.warning("Duplicate dispatch ignored — %s already in flight", key)
                return DispatchResult(
                    order_id=key, status=DispatchStatus.REJECTED,
                    strategy=strategy.strategy_name, underlying=strategy.underlying,
                    fills=[], error="duplicate_inflight",
                )
            self._inflight.add(key)
        try:
            return await self.submit_atomic(strategy, dry_run=dry_run)
        finally:
            async with self._lock:
                self._inflight.discard(key)
