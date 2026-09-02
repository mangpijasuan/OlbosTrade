"""
Opportunity Score — the same signal-quality ranking trade_frequency_controller
already uses to sort/gate signals, exposed as a single shared 0-100 display
score so Equity Signals, Options Signals, and Alpha Edge never show three
different numbers for the same underlying computation.

Not a new formula — trade_frequency_controller.weighted_score() rescaled
for display. See that module for the actual weights/math.
"""

from __future__ import annotations

from app.services.trade_frequency_controller import score_components, weighted_score


def compute_opportunity_score(signal: dict) -> dict:
    """Returns {"score": int 0-100, "components": {...}} for display."""
    return {
        "score": int(round(weighted_score(signal) * 100)),
        "components": {k: round(v, 4) for k, v in score_components(signal).items()},
    }
