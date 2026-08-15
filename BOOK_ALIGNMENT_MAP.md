# Algorithmic Trading Book -> OlbosTrade Alignment Map

## Source

Book reviewed:

- `Algorithmic Trading: Winning Strategies and Their Rationale` by Ernest P. Chan (2013)

This document answers a narrow question:

- how should this book influence `olbostrade`?

It is **not** a platform blueprint.
It is a **strategy research and validation reference** that should feed selected parts of the product.

## Overall Fit

The book aligns well with these parts of `olbostrade`:

- [backend/app/services/backtester.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/backtester.py)
- [backend/app/services/strategy_optimizer.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/strategy_optimizer.py)
- [backend/app/services/regime_classifier.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/regime_classifier.py)
- [backend/app/services/signal_scorer.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/signal_scorer.py)
- [backend/app/services/risk_manager.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/risk_manager.py)
- [backend/app/services/unified_risk.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/unified_risk.py)
- [frontend/src/pages/Backtest.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Backtest.tsx)
- [frontend/src/pages/Research.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Research.tsx)
- [frontend/src/pages/Strategy.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Strategy.tsx)

The book does **not** directly solve these parts of `olbostrade`:

- multi-broker execution architecture
- canonical order/fill/position/account models
- reconciliation-first operations
- kill-switch workflow design
- production broker diagnostics
- margin/buying-power truth across brokers

So the right role for this book is:

- strategy philosophy
- backtesting discipline
- regime-aware signal ideas
- practical risk thinking

Not:

- production architecture
- brokerage infrastructure
- modern operator terminal design

## Chapter-by-Chapter Import Map

## Chapter 1: Backtesting and Automated Execution

### Strong alignment

This is the chapter with the cleanest fit.

It directly supports:

- backtest realism
- live-vs-backtest consistency
- implementation discipline
- execution-aware strategy design

### Import into OlbosTrade

Use this chapter to strengthen:

- slippage modeling in the backtester
- transaction-cost modeling
- walk-forward validation
- backtest/live configuration parity
- event-driven execution assumptions

### Map to current code

- [backend/app/services/backtester.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/backtester.py)
- [backend/app/services/execution_dispatcher.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/execution_dispatcher.py)
- [backend/app/services/trade_recorder.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/trade_recorder.py)
- [frontend/src/pages/Backtest.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Backtest.tsx)

### Import now

- explicit slippage/fee presets by broker and asset class
- backtest assumptions panel in UI
- live-vs-backtest discrepancy tracking
- clearer execution quality metadata on strategies

### Adapt carefully

The book treats automated execution more generally than our current options-spread stack.
For `olbostrade`, execution must stay tied to:

- partial-fill handling
- multi-leg atomicity
- flatten fallback
- broker-specific constraints

### Do not import literally

- any execution assumption that ignores spread-leg coordination
- any simplified live-trading logic that bypasses current guardrails

## Chapter 2: The Basics of Mean Reversion

### Strong alignment

This chapter fits the research and signal layer very well.

It is especially useful for:

- ETF baskets
- equity pairs
- regime-aware mean reversion scanners
- cross-sectional signal ranking

### Import into OlbosTrade

Use it as a research source for:

- stationarity scoring
- half-life estimation
- spread-health diagnostics
- regime-conditioned mean reversion filters

### Map to current code

- [backend/app/services/regime_classifier.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/regime_classifier.py)
- [backend/app/services/strategy_registry.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/strategy_registry.py)
- [frontend/src/pages/Research.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Research.tsx)
- [frontend/src/pages/Strategy.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Strategy.tsx)

### Import now

- research metrics for half-life and spread z-score persistence
- validated-preset tags for mean-reversion families
- “why this should work” notes attached to strategy cards

### Adapt carefully

Most of this chapter is stronger for:

- equities
- ETFs
- futures

For options, the mean-reversion logic should usually drive:

- underlying selection
- regime gating
- entry timing

Not:

- direct option-price mean reversion assumptions

## Chapter 3: Implementing Mean Reversion Strategies

### Strong alignment

This fits the strategy design workflow, especially for:

- scanner construction
- prototype strategy generation
- parameter validation
- signal explanation

### Import into OlbosTrade

Use it to shape:

- prototype signal templates
- preset design
- calibration rules
- strategy validation notes

### Map to current code

- [backend/app/services/strategy_engine.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/strategy_engine.py)
- [backend/app/services/strategy_config_service.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/strategy_config_service.py)
- [backend/app/services/strategy_optimizer.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/strategy_optimizer.py)
- [frontend/src/pages/Strategy.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Strategy.tsx)

### Import now

- parameter provenance on presets
- stronger notes on why a preset is validated
- strategy health metrics beyond a single score

### Adapt carefully

Do not allow research-stage mean-reversion prototypes to bypass the lifecycle model.
Everything imported from this chapter should still pass through:

- registry
- preset validation
- snapshot activation
- autopilot eligibility checks

## Chapter 4: Mean Reversion of Stocks and ETFs

### High alignment for expansion

This chapter is one of the best sources for expanding the equity side of the platform.

It fits:

- equity scanners
- ETF rotation ideas
- pair/triplet research
- market-neutral baskets

### Map to current code

- [frontend/src/pages/EquitySignals.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/EquitySignals.tsx)
- [backend/app/services/equity_signal_engine.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/equity_signal_engine.py)
- [backend/app/services/signal_scorer.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/signal_scorer.py)

### Import now

- ETF basket scanner
- pair relationship research panel
- sector-relative mean-reversion scanners
- signal-quality diagnostics for equity baskets

### Adapt carefully

This chapter is more naturally aligned with:

- single-name equity trades
- ETF spread trades

Than with:

- multi-leg options structures

The best adaptation is to use these ideas for:

- underlying selection
- directional bias
- hedge ratio intuition

Then route them into options structures where appropriate.

## Chapter 5: Mean Reversion of Currencies and Futures

### Partial alignment

This chapter is useful, but less central for the current product unless `olbostrade` expands into:

- futures
- FX
- volatility products

### Import into OlbosTrade

Use it as a deferred research lane, not a near-term build driver.

### Import later

- futures calendar-spread research framework
- roll-return analytics
- contango/backwardation regime logic

### Low-priority fit today

Current platform focus remains stronger in:

- equities
- options
- broker-safe retail automation

So this chapter should not drive near-term core implementation.

## Chapter 6: Interday Momentum Strategies

### Strong alignment

This chapter fits very well with:

- swing-trading signal logic
- ETF momentum baskets
- regime-aware directional strategies

### Map to current code

- [backend/app/services/regime_classifier.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/regime_classifier.py)
- [backend/app/services/signal_scorer.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/signal_scorer.py)
- [frontend/src/pages/EquitySignals.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/EquitySignals.tsx)

### Import now

- momentum strategy family in the registry
- interday momentum presets
- regime-conditioned momentum eligibility
- equity basket momentum panel

### Adapt carefully

Momentum imported from this chapter should be mode-aware:

- `Manual`: idea support
- `Copilot`: gated suggestion
- `Autopilot`: only after stronger live validation

This is especially important because momentum is more execution-sensitive than many simplified backtests imply.

## Chapter 7: Intraday Momentum Strategies

### Selective alignment

This is where the book starts to drift away from the platform’s current operational strengths.

The ideas are still useful, but only selectively.

### Best fit

Use this chapter for:

- intraday scanner ideas
- order-flow-inspired heuristics
- session-structure awareness

### Weak fit today

Avoid using this chapter as justification for immediately building:

- high-frequency trading behavior
- aggressive microstructure-sensitive intraday systems
- latency-dependent execution promises

`olbostrade` is not yet a low-latency intraday momentum engine.
Its current architecture is still being hardened around:

- reconciliation
- canonical state
- broker-safe automation

### Import now

- session-aware scanner states
- intraday caution flags
- “execution-sensitive” labels on certain strategies

### Defer

- serious intraday momentum autopilot
- anything that assumes microsecond or venue-level edge

## Chapter 8: Risk Management

### Very strong alignment

This is one of the most important chapters for the platform.

It aligns tightly with:

- guardrails
- unified risk
- capital preservation
- leverage discipline
- tail-risk awareness

### Map to current code

- [backend/app/services/risk_manager.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/risk_manager.py)
- [backend/app/services/unified_risk.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/unified_risk.py)
- [backend/app/services/position_reconciler.py](/Users/mangpijasuan/Projects/olbostrade/backend/app/services/position_reconciler.py)
- [frontend/src/pages/Guardrails.tsx](/Users/mangpijasuan/Projects/olbostrade/frontend/src/pages/Guardrails.tsx)

### Import now

- MFE / MAE tracking on closed trades
- stress-test scenarios in backtest and risk views
- leverage sanity overlays
- stronger risk explanations in the terminal

### Adapt carefully

The book’s risk treatment is useful, but our platform needs more broker-native operational truth than the book emphasizes.
So combine the book’s ideas with the current platform priorities:

- buying power truth
- margin utilization
- reconciliation state
- kill-switch confirmation

## What To Import First

If we use the book well, the first batch should be:

1. MFE / MAE journaling
2. stronger backtest assumptions and slippage modeling
3. momentum and mean-reversion strategy families in the registry
4. ETF/equity scanner upgrades
5. stress-test scenarios in risk and backtest views

## What To Defer

Do not let the book pull the roadmap away from current platform priorities.

Defer:

- FX/futures expansion as a core product priority
- high-frequency or microstructure-heavy intraday systems
- any strategy import that weakens the fail-closed execution path
- any architecture decision justified only by older market-structure assumptions

## Recommended Product Use

The best product-level home for this book is:

- `Research` for thesis building
- `Strategy Registry` for strategy-family design
- `Backtest` for validation discipline
- `Guardrails` for risk ideas
- `Equity Signals` for ETF/equity scanner expansion

The worst use would be treating it as:

- the platform architecture manual
- the broker integration playbook
- the live execution safety standard

## Final Guidance

This book **does align with OlbosTrade**, but mostly as a:

- strategy playbook
- validation discipline reference
- risk-thinking source

It should shape what strategies we research and how we validate them.

It should **not** replace the current architecture direction around:

- multi-broker design
- canonical state
- reconciliation
- safety-first execution
- modern retail automation controls
