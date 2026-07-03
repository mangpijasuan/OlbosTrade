# OlbosQuant Approved Architecture Memo

## Purpose

This memo reframes the earlier viability report into an engineering-aligned architecture note for the current `olbosquant` codebase. It keeps the strong parts of the original thesis, corrects a few mis-prioritized points, and defines the next system-level build order.

The intended product remains the same:

- one flagship institutional-grade retail automated trading platform
- multi-broker by design
- IBKR and Alpaca as primary brokers
- market data separated from execution
- one canonical portfolio/account/order model
- Manual / Copilot / Autopilot modes
- safety-first operator terminal

## Executive Position

The system already has several strong foundations:

- broker abstraction exists and supports IBKR and Alpaca
- execution is already guarded by a safety-first pipeline
- market data is intentionally decoupled from execution
- strategy registry, presets, and snapshots now exist
- kill switch and guardrail flows are present

However, the platform is not yet "institutional-grade" in the operational sense.

The biggest remaining gaps are not visual polish or feature breadth. They are:

1. canonical execution/account state
2. reconciliation truth
3. broker-event streaming
4. margin and buying power visibility
5. full audit lineage from signal -> order -> fill -> position -> exit

That means the right question is not "is the UI advanced enough?" but "can the system always tell the truth about risk, orders, fills, and positions across brokers?"

## What We Agree With From The Report

The original note is directionally correct on these points:

- kill switch must be treated as a top-tier safety system
- strategy attribution and execution lineage must be strict
- risk and execution views should move from polling toward streaming
- margin and buying power tracking are mandatory for live automation
- MFE / MAE journaling is high-value and should be added
- stress testing should extend beyond historical replay
- embedded AI research assistant should be deferred
- behavioral analytics should stay lightweight for now

## What We Would Reframe

### 1. Kill Switch: backend truth matters more than transport choice

The report emphasizes WebSocket delivery, but the higher-order issue is backend atomicity and confirmation.

Current state:

- the kill switch endpoint already exists in [backend/app/api/routes/risk.py](backend/app/api/routes/risk.py)
- it cancels orders, flattens positions, and returns partial-error status when needed

What still matters more than adding a WebSocket button:

- halt signal generation immediately
- confirm broker cancel/flatten acknowledgements
- persist a kill-switch event record
- run reconciliation after kill-switch completion
- fail closed if flattening is partial

Conclusion:

- WebSocket activation is a useful UX improvement
- it is not the core architectural fix
- the core fix is a confirmed, auditable, reconciliation-aware emergency workflow

### 2. Database integrity is not only foreign keys

The report is right that attribution must never become `UNKNOWN`, but strict foreign keys alone are not enough.

Current state:

- trade snapshot linkage exists via migration [backend/alembic/versions/0008_add_strategy_presets_and_snapshots.py](backend/alembic/versions/0008_add_strategy_presets_and_snapshots.py)
- fills are recorded with active strategy snapshots in [backend/app/services/trade_recorder.py](backend/app/services/trade_recorder.py)

What is still missing:

- canonical order record
- canonical fill record
- broker execution id mapping
- internal order lifecycle status model
- normalized position identity across brokers
- signal-to-order linkage as a first-class entity

Conclusion:

- keep the current snapshot linkage
- extend it into full execution lineage, not just stronger table constraints

### 3. Streaming should start with execution and risk, not every panel

The report is correct that live trading should not rely heavily on polling. But not every part of the product deserves streaming first.

Recommended order:

1. broker connectivity and heartbeat events
2. order status and fill events
3. reconciliation exceptions
4. portfolio exposure, margin, buying power, guardrail state
5. live signal validity updates
6. lower-priority UI telemetry panels

Conclusion:

- streaming is necessary
- start with broker/event/risk truth, not ticker cosmetics

### 4. The frontend is promising, not yet institutional

The operator terminal is getting stronger and the UX direction is good. But the system still lacks a few controls that institutional-grade software would require:

- one canonical order/account/portfolio domain model
- reconciliation-first operations
- margin utilization truth
- broker disconnect failover behavior
- event-sourced execution audit trail
- persistent alerting and incident review flows

Conclusion:

- the frontend is a strong shell
- the system becomes institutional-grade only when operational truth is stronger than display fidelity

## Current Codebase Strengths

### 1. Broker abstraction and multi-broker direction

The repo already follows the correct base decision:

- execution is abstracted behind broker clients
- IBKR and Alpaca are already supported
- options/equities coexist within the same architecture

This should remain the base platform shape.

### 2. Execution pipeline and guardrails

The audit trail in [backend/AUDIT.md](backend/AUDIT.md) shows that the system has already been pushed toward a single fail-closed execution path.

This is the right foundation for:

- Manual mode
- Copilot approvals
- Autopilot dispatch

All three should continue to route through one canonical approval and execution path.

### 3. Separation of market data from execution

The current market-data route design is already aligned with the target architecture:

- yfinance and display-oriented data are separate from broker execution concerns
- IBKR is not treated as the sole source for UI market display

This should be preserved and strengthened.

### 4. Strategy lifecycle model

Strategy registry, verified presets, and snapshots are now in place. That is a strong system-level improvement because it allows:

- lifecycle gating
- validated configuration baselines
- safer strategy activation
- traceable configuration at entry time

This should stay and become more deeply connected to orders, fills, and analytics.

## Current Gaps That Matter Most

### 1. No fully canonical order/fill/position model yet

This is the most important remaining architecture gap.

The platform needs one normalized internal model for:

- broker account
- buying power and margin state
- order intent
- order lifecycle
- execution fills
- open positions
- closed trades

Broker adapters should translate broker-specific payloads into this model.

### 2. Reconciliation is not yet the operating center of the system

A live automated platform must constantly compare:

- internal DB state
- broker open orders
- broker fills
- broker positions
- expected strategy state

Reconciliation should not be a passive helper. It should be an active service with:

- periodic jobs
- drift detection
- severity levels
- operator alerts
- safe degradation or autopilot pause on unresolved mismatches

### 3. Margin and buying power are still under-modeled

Nominal P&L limits are not enough for options automation.

The platform needs normalized live fields for:

- net liquidation
- cash
- buying power
- initial margin
- maintenance margin
- margin utilization percent
- buying power reduction by strategy and by position

Without this, autopilot can look profitable while still walking into forced broker liquidation risk.

### 4. Execution lineage is still incomplete

The system now records strategy snapshots on trades, which is good. But complete lineage still requires:

- signal id
- strategy id
- strategy snapshot id
- internal order id
- broker order id
- broker execution id
- fill timestamps
- reconciliation status
- exit linkage

This should become queryable and auditable in one place.

### 5. Streaming/event transport is missing where it matters most

The live system should push updates for:

- broker status
- order submitted / accepted / partially filled / filled / cancelled / rejected
- reconciliation exceptions
- guardrail transitions
- kill-switch state changes
- margin threshold warnings

This is a better first streaming target than general dashboard animation.

## Recommended Architecture

### Core layers

1. **Broker Adapters**
   - `IBKRAdapter`
   - `AlpacaAdapter`
   - broker-specific normalization only

2. **Canonical Domain Layer**
   - `CanonicalAccount`
   - `CanonicalPortfolio`
   - `CanonicalOrder`
   - `CanonicalFill`
   - `CanonicalPosition`
   - `CanonicalExecutionEvent`

3. **Execution Core**
   - current OMS / dispatcher / fill handling stays the base
   - all order paths route through one service boundary
   - partial-fill handling and flatten fallback stay mandatory

4. **Risk and Guardrail Layer**
   - pre-trade approval
   - portfolio exposure limits
   - margin and buying power gating
   - mode-aware permissions
   - hard fail-closed behavior

5. **Reconciliation Layer**
   - broker truth vs DB truth comparison
   - order drift detection
   - position mismatch detection
   - stale or orphan execution detection

6. **Strategy Lifecycle Layer**
   - registry
   - presets
   - snapshots
   - validation state
   - autopilot eligibility

7. **Operator Terminal Layer**
   - strategy pages
   - trade desk
   - diagnostics
   - macro context
   - scanners
   - alerts

### Data ownership principle

- execution truth comes from normalized broker events plus reconciliation
- market display truth comes from market-data services
- strategy truth comes from registry + snapshots + lifecycle rules
- risk truth comes from canonical portfolio state, not ad hoc page-level calculations

## What To Build Next

### Phase 1: Canonical state and reconciliation

Build first:

- canonical order/fill/position/account models
- reconciliation service
- reconciliation status table and alerts
- broker execution id storage
- unresolved mismatch dashboard panel

Why first:

- this is the base for safe multi-broker automation
- it improves trust in every other feature

### Phase 2: Margin and buying power engine

Build:

- normalized broker account ingestion
- buying power and margin utilization fields
- risk dashboard exposure panel
- autopilot margin gates
- per-strategy capital consumption visibility

Why second:

- this closes one of the biggest live-trading failure modes

### Phase 3: Event streaming

Build:

- backend event bus or WebSocket gateway
- order/fill/risk/reconciliation streams
- terminal subscriptions for trade desk, risk, and broker diagnostics

Why third:

- once state is canonical, streaming can distribute truth cleanly

### Phase 4: Trade analytics and stress tooling

Build:

- MFE / MAE on closed trades
- scenario stress tests
- shock analysis for VIX and index gap moves
- strategy efficiency analytics by regime

Why fourth:

- analytics become more useful after state and reconciliation are trustworthy

### Phase 5: Lower-priority product enhancements

Defer:

- embedded AI research assistant
- heavy behavioral dashboards
- non-critical UI novelty features

## Product Scope Guidance

### Keep

- broker abstraction
- OMS / execution core
- risk engine
- guardrails
- backtesting
- options/equities architecture
- strategy lifecycle registry

### Bring forward from the terminal vision

- cleaner operator UX
- broker diagnostics
- deploy and production ergonomics
- practical scanners
- macro context panels

### Retire or defer

- AI assistant inside the terminal
- deep behavior-analysis features for discretionary trading psychology
- non-essential dashboard complexity before operational truth is solved

## Final Recommendation

The platform should continue building on `olbosquant`, not restart from scratch.

Why:

- the right execution and risk foundations already exist
- multi-broker direction is already present
- strategy lifecycle work has already started
- recent fixes moved the system toward fail-closed behavior

But the next bar for progress is clear:

`olbosquant` should now behave less like a feature-rich trading app and more like a state-truth machine for orders, fills, risk, and broker reconciliation.

That is the shortest path to a real flagship institutional-grade retail platform.
