"""
Realistic fill simulator for backtesting.
Models vol-regime-aware bid-ask slippage, partial fill simulation,
commissions, and minimum fills.

FIX #7: Vol-adjusted slippage — spread expansion is non-linear with VIX.
FIX #7: Multi-leg partial fill simulation — combo orders do not always fill atomically.
Never use market prices directly in backtests — always run through this module.
"""

import random
from dataclasses import dataclass
from typing import Literal, Optional

# IBKR standard options commission
COMMISSION_PER_CONTRACT = 0.65

# Options rarely fill below this in practice
MINIMUM_FILL_PRICE = 0.05

# Slippage as a fraction of the bid-ask spread — STATIC fallback only
# Use vol_adjusted_slippage_pct() for all live/backtest paths
SLIPPAGE_MAP: dict[str, float] = {
    "tight": 0.05,
    "normal": 0.10,
    "wide": 0.25,
}

# Partial fill probability by VIX regime
# In stressed markets, combo orders frequently partially fill
PARTIAL_FILL_PROBABILITY: dict[str, float] = {
    "tight": 0.97,   # VIX < 20: 97% chance all legs fill
    "normal": 0.90,  # VIX 20–30: 90%
    "wide": 0.72,    # VIX 30+: only 72% chance of full atomic fill
}


def vix_to_liquidity(vix: float) -> Literal["tight", "normal", "wide"]:
    """Map VIX level to liquidity regime."""
    if vix < 20:
        return "tight"
    elif vix < 30:
        return "normal"
    else:
        return "wide"


def vol_adjusted_slippage_pct(vix: float) -> float:
    """
    FIX #7: Slippage scales non-linearly with VIX.

    Below 20: tight market — 10% of spread
    20–30:    normal — scales linearly from 20% → 40%
    30+:      stressed — scales up to 65% cap

    Returns slippage as a fraction of bid-ask spread.
    """
    if vix < 20:
        return 0.10
    elif vix < 30:
        # Linear scale: 20% at VIX=20, 40% at VIX=30
        return 0.20 + (vix - 20) * 0.02
    else:
        # Continues scaling, hard cap at 65%
        return min(0.40 + (vix - 30) * 0.03, 0.65)


@dataclass(frozen=True)
class FillResult:
    """Complete fill result including net cost after commissions."""
    gross_fill_price: float
    commission: float
    net_fill_price: float
    contracts: int
    net_cost: float


@dataclass
class SpreadFillResult:
    """
    FIX #7: Result of a multi-leg spread fill attempt.
    combo_complete=False means a partial fill occurred — caller MUST handle
    the naked position that results from unfilled legs.
    """
    leg_fills: list[FillResult]
    combo_complete: bool
    legs_filled: int
    legs_total: int
    partial_fill_reason: Optional[str] = None

    def __len__(self) -> int:
        """Backward-compatible length as the number of filled legs."""
        return len(self.leg_fills)

    def __iter__(self):
        """Allow legacy callers/tests to iterate over leg fills directly."""
        return iter(self.leg_fills)

    def __getitem__(self, index: int) -> FillResult:
        """Allow legacy list-style access to individual leg fills."""
        return self.leg_fills[index]


def realistic_fill_price(
    bid: float,
    ask: float,
    side: Literal["BUY", "SELL"],
    liquidity: Literal["tight", "normal", "wide"] = "normal",
    vix: Optional[float] = None,
) -> float:
    """
    Calculate a realistic fill price given bid/ask and market conditions.

    FIX #7: When vix is provided, uses vol-adjusted slippage instead of
    static slippage_map. Always prefer passing vix in backtests.

    BUY orders fill above mid (you pay more).
    SELL orders fill below mid (you receive less).
    Fill is floored at MINIMUM_FILL_PRICE.
    """
    if bid < 0 or ask < 0:
        raise ValueError(f"Bid/ask cannot be negative: bid={bid}, ask={ask}")
    if ask < bid:
        raise ValueError(f"Ask must be >= bid: bid={bid}, ask={ask}")

    mid = (bid + ask) / 2

    # FIX #7: Use VIX-aware slippage when available
    if vix is not None:
        slippage_pct = vol_adjusted_slippage_pct(vix)
    else:
        slippage_pct = SLIPPAGE_MAP[liquidity]

    slippage = (ask - bid) * slippage_pct

    fill = mid + slippage if side == "BUY" else mid - slippage
    return max(fill, MINIMUM_FILL_PRICE)


class FillSimulator:
    """
    Full fill simulator for multi-contract options orders.
    Applies vol-regime-aware slippage + IBKR-rate commissions.
    Simulates partial fills for multi-leg combo orders.
    Use this for every trade in the backtester.
    """

    def __init__(
        self,
        commission_per_contract: float = COMMISSION_PER_CONTRACT,
        minimum_fill: float = MINIMUM_FILL_PRICE,
        random_seed: Optional[int] = None,
    ) -> None:
        self.commission_per_contract = commission_per_contract
        self.minimum_fill = minimum_fill
        if random_seed is not None:
            random.seed(random_seed)

    def simulate_fill(
        self,
        bid: float,
        ask: float,
        side: Literal["BUY", "SELL"],
        contracts: int = 1,
        liquidity: Literal["tight", "normal", "wide"] = "normal",
        vix: Optional[float] = None,
    ) -> FillResult:
        """
        Simulate a realistic fill for a single-leg options order.

        Args:
            bid:       Current bid
            ask:       Current ask
            side:      "BUY" or "SELL"
            contracts: Number of option contracts (each = 100 shares)
            liquidity: Market liquidity level (overridden by vix if provided)
            vix:       Current VIX level — enables vol-adjusted slippage

        Returns:
            FillResult with gross price, commission, net price, and net cost.
        """
        if contracts <= 0:
            raise ValueError(f"contracts must be positive, got {contracts}")

        # FIX #7: Derive liquidity from VIX if provided
        effective_liquidity = vix_to_liquidity(vix) if vix is not None else liquidity

        gross = realistic_fill_price(bid, ask, side, effective_liquidity, vix)
        commission = self.commission_per_contract * contracts
        multiplier = 100  # standard options contract multiplier

        if side == "BUY":
            net_fill = gross + (commission / (contracts * multiplier))
            net_cost = gross * contracts * multiplier + commission
        else:
            net_fill = gross - (commission / (contracts * multiplier))
            net_cost = -(gross * contracts * multiplier - commission)

        return FillResult(
            gross_fill_price=round(gross, 4),
            commission=round(commission, 4),
            net_fill_price=round(net_fill, 4),
            contracts=contracts,
            net_cost=round(net_cost, 4),
        )

    def simulate_spread_fill(
        self,
        legs: list[dict],
        contracts: int = 1,
        liquidity: Literal["tight", "normal", "wide"] = "normal",
        vix: Optional[float] = None,
        simulate_partial_fills: bool = True,
    ) -> SpreadFillResult:
        """
        FIX #7: Simulate fills for all legs of a spread with partial fill risk.

        In real markets, combo orders are NOT atomic. During stressed conditions
        (high VIX), individual legs may fail to fill, leaving a naked position.
        This simulator models that risk.

        Args:
            legs:                    List of {"bid", "ask", "side"} dicts
            contracts:               Number of spreads
            liquidity:               Regime (overridden by vix)
            vix:                     Current VIX — determines partial fill probability
            simulate_partial_fills:  Set False only for unit tests

        Returns:
            SpreadFillResult — ALWAYS check combo_complete before assuming
            the full spread was established.
        """
        effective_liquidity = vix_to_liquidity(vix) if vix is not None else liquidity
        fill_prob = PARTIAL_FILL_PROBABILITY[effective_liquidity]

        leg_fills: list[FillResult] = []

        for i, leg in enumerate(legs):
            # FIX #7: Stochastic partial fill — each leg has independent fill probability
            if simulate_partial_fills and random.random() > fill_prob:
                return SpreadFillResult(
                    leg_fills=leg_fills,
                    combo_complete=False,
                    legs_filled=i,
                    legs_total=len(legs),
                    partial_fill_reason=(
                        f"Leg {i+1}/{len(legs)} failed to fill "
                        f"(VIX={vix:.1f}, fill_prob={fill_prob:.0%})"
                        if vix else f"Leg {i+1}/{len(legs)} failed to fill"
                    ),
                )

            fill = self.simulate_fill(
                bid=leg["bid"],
                ask=leg["ask"],
                side=leg["side"],
                contracts=contracts,
                liquidity=effective_liquidity,
                vix=vix,
            )
            leg_fills.append(fill)

        return SpreadFillResult(
            leg_fills=leg_fills,
            combo_complete=True,
            legs_filled=len(legs),
            legs_total=len(legs),
        )
