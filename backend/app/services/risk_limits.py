"""
Shared Greeks and risk limit constants.

Single source of truth for delta/vega/theta limits used by both RiskManager
and PortfolioGreeksTracker.  Import from here — never define these numbers
in two places.

Adjust values here and both enforcement layers update automatically.
"""

# Maximum |net portfolio delta| as a fraction of portfolio value.
# Breaching this triggers a delta-limit refusal in RiskManager and flags
# needs_hedge() in PortfolioGreeksTracker.
MAX_PORTFOLIO_DELTA: float = 0.30

# Maximum |net portfolio vega| as a fraction of portfolio value.
# Breaching this triggers a vega-limit refusal in RiskManager and flags
# vega_at_limit() in PortfolioGreeksTracker.
MAX_PORTFOLIO_VEGA: float = 0.15
