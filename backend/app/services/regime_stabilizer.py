"""
Regime stabilizer — hysteresis on regime changes.

WHY THIS EXISTS
---------------
`RegimeClassifier.classify()` is a pure function of the current reading, with
no memory. Several of its decisions sit on knife-edges of continuous inputs,
and the sharpest is the 5-day return crossing `TREND_ADX_THRESHOLD`'s sibling
`TREND_RETURN_5D = 0.03`. In an ordinary normal-vol market (IV rank ~42, RSI
~50) a move of one basis point in the 5-day return is the whole decision:

    5d return 2.99%  ->  normal_mean_revert   iron condor ON   size 100%  thr 0.65
    5d return 3.00%  ->  high_vol_trending    iron condor OFF  size  75%  thr 0.72

Nothing smooths that. `_reclassify_regime()` runs every 30 minutes against
DAILY bars whose last bar is the still-forming session, so the 5-day return
moves intraday and the boundary is re-sampled ~13 times a trading day. A market
sitting near the threshold re-decides strategy allocation, position size and
the signal bar over and over, within the same day.

That is strategy hopping — the exact discipline failure the guardrails protect
the operator from — happening at machine speed inside the system.

WHAT THIS DOES
--------------
A regime change is adopted only after `required` consecutive classifications
agree on it. A single divergent reading is remembered but not acted on, and a
reading that disagrees with the pending candidate resets the count.

The asymmetry matters more than the count: CRISIS is adopted the instant it is
seen. Risk-off is never delayed. Leaving CRISIS requires confirmation like any
other change, so one calm reading cannot put capital back to work.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not withhold FRESHNESS. `_ensure_fresh_regime()` resets the regime to
UNKNOWN when `classified_at` is older than MAX_REGIME_AGE_SECONDS (2h), and a
hold can legitimately last longer than that. Returning the stale state object
unchanged would trip that gate and slam everything to UNKNOWN — a worse outcome
than the churn this is fixing. So a held decision is returned with a REFRESHED
`classified_at`: the classification did happen and the data is current; we are
choosing to keep the previous conclusion. The staleness gate keeps meaning
"we have not been able to read the market", which is a different fault.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

from app.services.regime_classifier import RegimeState, RegimeType
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class StabilizedRegime:
    """The regime in force, plus what the raw classifier actually said."""
    state:         RegimeState           # what the rest of the system should use
    raw:           RegimeType            # what this reading classified
    pending:       Optional[RegimeType]  # candidate awaiting confirmation
    pending_count: int                   # consecutive readings backing it
    required:      int                   # readings needed to adopt
    held:          bool                  # True when a change is being withheld

    @property
    def changed(self) -> bool:
        """True when this observation adopted a new regime."""
        return not self.held and self.raw != self.pending and self.pending_count == 0


class RegimeStabilizer:
    """
    Stateful gate in front of the stateless classifier.

    Not merged into RegimeClassifier on purpose: `classify()` stays a pure
    function that is trivial to test and reason about, and the hysteresis
    policy stays independently testable without constructing IV surfaces.
    """

    #: Adopted the moment it is seen — de-risking is never delayed.
    IMMEDIATE: frozenset[RegimeType] = frozenset({RegimeType.CRISIS})

    def __init__(self, required: int = 3) -> None:
        #: 1 disables the guard entirely (every reading adopted), which is the
        #: pre-guard behaviour and the documented escape hatch.
        self.required = max(1, int(required))
        self._current: Optional[RegimeState] = None
        self._pending: Optional[RegimeType] = None
        self._count = 0

    @property
    def current(self) -> Optional[RegimeState]:
        return self._current

    def observe(self, state: RegimeState) -> StabilizedRegime:
        """Feed one classification in; get the regime that should be in force."""
        now = datetime.now(timezone.utc)
        incoming = state.regime

        # Cold start — nothing to be stable about yet.
        if self._current is None:
            self._current = state
            self._pending, self._count = None, 0
            logger.info("Regime stabilizer: initial regime %s", incoming.value)
            return StabilizedRegime(state, incoming, None, 0, self.required, held=False)

        # Unchanged. Take the NEW object so confidence, features and
        # classified_at all move forward; only the decision is sticky.
        if incoming == self._current.regime:
            self._current = state
            self._pending, self._count = None, 0
            return StabilizedRegime(state, incoming, None, 0, self.required, held=False)

        # De-risking overrides hysteresis.
        if incoming in self.IMMEDIATE:
            logger.warning(
                "Regime stabilizer: %s -> %s adopted IMMEDIATELY (risk-off is never delayed)",
                self._current.regime.value, incoming.value,
            )
            self._current = state
            self._pending, self._count = None, 0
            return StabilizedRegime(state, incoming, None, 0, self.required, held=False)

        # A change. Count consecutive agreement.
        if incoming == self._pending:
            self._count += 1
        else:
            self._pending, self._count = incoming, 1

        if self._count >= self.required:
            logger.info(
                "Regime stabilizer: %s -> %s adopted after %d consecutive readings",
                self._current.regime.value, incoming.value, self._count,
            )
            self._current = state
            self._pending, self._count = None, 0
            return StabilizedRegime(state, incoming, None, 0, self.required, held=False)

        logger.info(
            "Regime stabilizer: holding %s — %s seen %d/%d times, not yet adopted",
            self._current.regime.value, incoming.value, self._count, self.required,
        )
        held_state = replace(
            self._current,
            classified_at=now,
            reasoning=list(self._current.reasoning) + [
                f"stabilizer: classifier said {incoming.value} "
                f"({self._count}/{self.required} readings) — change withheld"
            ],
        )
        self._current = held_state
        return StabilizedRegime(
            held_state, incoming, self._pending, self._count, self.required, held=True
        )
