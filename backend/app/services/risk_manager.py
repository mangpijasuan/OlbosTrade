"""
Portfolio-level risk manager.
Enforces Greeks limits, concentration limits, and per-trade sizing.
Works alongside GuardrailEngine — both must approve before a trade executes.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from app.core.config import settings
from app.services.risk_limits import MAX_PORTFOLIO_DELTA as _MAX_PORTFOLIO_DELTA, MAX_PORTFOLIO_VEGA as _MAX_PORTFOLIO_VEGA
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TradeApproval:
    """Result of a risk manager trade check."""
    approved: bool
    reason: Optional[str]
    suggested_contracts: int
    max_risk_dollars: float
    flags: list[str] = field(default_factory=list)


@dataclass
class PortfolioRiskState:
    """Current portfolio Greeks and concentration state."""
    net_delta: float
    net_vega: float
    net_theta: float
    open_position_count: int
    portfolio_value: float
    positions_by_underlying: dict[str, float]   # underlying -> notional exposure
    positions_by_sector: dict[str, float]        # sector -> notional exposure


@dataclass
class ProposedTrade:
    """A trade being evaluated for risk approval."""
    strategy: str
    underlying: str
    sector: str
    delta: float
    vega: float
    max_loss_dollars: float
    contracts: int = 1


class RiskManager:
    """
    Portfolio-level risk guard.
    Called via approve_trade() before every order submission.
    """

    MAX_PORTFOLIO_DELTA = _MAX_PORTFOLIO_DELTA
    MAX_VEGA_EXPOSURE = _MAX_PORTFOLIO_VEGA
    MAX_CONCURRENT_POSITIONS = 5
    MAX_SINGLE_UNDERLYING = 0.25       # 25% of portfolio in one underlying
    MAX_SECTOR_CONCENTRATION = 0.40    # 40% of portfolio in one sector
    RISK_PER_TRADE_PCT = 0.02          # 2% portfolio risk per trade

    def __init__(self) -> None:
        self.max_concurrent = settings.max_concurrent_positions

    def calculate_position_size(
        self,
        portfolio_value: float,
        max_loss_per_spread: float,
        risk_pct: float = RISK_PER_TRADE_PCT,
        size_multiplier: float = 1.0,
    ) -> int:
        """
        Calculate number of contracts to trade given risk parameters.

        Args:
            portfolio_value:    Current account value
            max_loss_per_spread: Max dollar loss if spread hits full stop (per contract)
            risk_pct:           Target risk as fraction of portfolio
            size_multiplier:    1.0 normal, 0.5 in capital preservation mode

        Returns:
            Number of contracts (minimum 1).
        """
        target_risk = portfolio_value * risk_pct * size_multiplier
        contracts = int(target_risk / max(max_loss_per_spread, 1.0))
        return max(contracts, 0)  # 0 is valid — caller must skip the trade

    def kelly_position_size(
        self,
        portfolio_value: float,
        win_rate: float,
        avg_win_pct: float,
        avg_loss_pct: float,
        kelly_fraction: float = 0.25,
    ) -> float:
        """
        Kelly-optimal position size in dollars, fractional Kelly at 0.25.
        Falls back to 2% risk when inputs are invalid.
        """
        if avg_win_pct <= 0 or win_rate <= 0 or win_rate >= 1:
            return portfolio_value * self.RISK_PER_TRADE_PCT

        edge = win_rate * avg_win_pct - (1 - win_rate) * abs(avg_loss_pct)
        kelly_full = edge / avg_win_pct if avg_win_pct > 0 else 0.0

        if kelly_full <= 0:
            return portfolio_value * self.RISK_PER_TRADE_PCT

        position_dollars = portfolio_value * kelly_full * kelly_fraction
        # Clamp: never more than 8% or less than 1% of portfolio
        return max(min(position_dollars, portfolio_value * 0.08), portfolio_value * 0.01)

    def approve_trade(
        self,
        trade: ProposedTrade,
        portfolio: PortfolioRiskState,
        size_multiplier: float = 1.0,
    ) -> TradeApproval:
        """
        Evaluate a proposed trade against all portfolio risk limits.
        Returns TradeApproval — approved must be True to proceed.
        """
        flags: list[str] = []

        # ── Position count limit ───────────────────────────────────────────
        if portfolio.open_position_count >= self.max_concurrent:
            return TradeApproval(
                approved=False,
                reason=f"Max concurrent positions reached: {portfolio.open_position_count}/{self.max_concurrent}",
                suggested_contracts=0,
                max_risk_dollars=0,
                flags=["max_positions"],
            )

        # ── Portfolio delta limit ──────────────────────────────────────────
        new_delta = abs(portfolio.net_delta + trade.delta)
        if new_delta > self.MAX_PORTFOLIO_DELTA:
            return TradeApproval(
                approved=False,
                reason=f"Portfolio delta limit breached: {new_delta:.3f} > {self.MAX_PORTFOLIO_DELTA}",
                suggested_contracts=0,
                max_risk_dollars=0,
                flags=["delta_limit"],
            )

        # ── Portfolio vega limit ───────────────────────────────────────────
        new_vega = abs(portfolio.net_vega + trade.vega)
        if new_vega > self.MAX_VEGA_EXPOSURE:
            return TradeApproval(
                approved=False,
                reason=f"Portfolio vega limit breached: {new_vega:.3f} > {self.MAX_VEGA_EXPOSURE}",
                suggested_contracts=0,
                max_risk_dollars=0,
                flags=["vega_limit"],
            )

        # ── Single underlying concentration ───────────────────────────────
        current_exposure = portfolio.positions_by_underlying.get(trade.underlying, 0.0)
        new_exposure = current_exposure + trade.max_loss_dollars
        if portfolio.portfolio_value > 0:
            exposure_pct = new_exposure / portfolio.portfolio_value
            if exposure_pct > self.MAX_SINGLE_UNDERLYING:
                return TradeApproval(
                    approved=False,
                    reason=(
                        f"Single underlying concentration limit: {trade.underlying} "
                        f"would be {exposure_pct:.1%} of portfolio (max {self.MAX_SINGLE_UNDERLYING:.0%})"
                    ),
                    suggested_contracts=0,
                    max_risk_dollars=0,
                    flags=["concentration_limit"],
                )

        # ── Sector concentration ───────────────────────────────────────────
        sector_exposure = portfolio.positions_by_sector.get(trade.sector, 0.0)
        new_sector_exposure = sector_exposure + trade.max_loss_dollars
        if portfolio.portfolio_value > 0:
            sector_pct = new_sector_exposure / portfolio.portfolio_value
            if sector_pct > self.MAX_SECTOR_CONCENTRATION:
                flags.append("sector_concentration_warning")
                logger.warning(
                    "Sector concentration elevated: %s at %.1f%%",
                    trade.sector, sector_pct * 100,
                )

        # ── Calculate position size ────────────────────────────────────────
        contracts = self.calculate_position_size(
            portfolio_value=portfolio.portfolio_value,
            max_loss_per_spread=trade.max_loss_dollars,
            size_multiplier=size_multiplier,
        )
        max_risk = contracts * trade.max_loss_dollars

        logger.info(
            "Risk approved: %s %s — %d contracts, max risk $%.2f",
            trade.strategy, trade.underlying, contracts, max_risk,
        )

        return TradeApproval(
            approved=True,
            reason=None,
            suggested_contracts=contracts,
            max_risk_dollars=max_risk,
            flags=flags,
        )
