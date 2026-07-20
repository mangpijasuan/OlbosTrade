# OlbosTrade — Institutional Trade Desk 2.0 — Master Spec

**Status:** canonical target architecture. This is the source of truth for what
"done" means going forward. `PLAN.md` tracks actual progress *against this
document* — do not mark a section "complete" here unless the code satisfies
the specific bullets below, not just a same-named component existing.

Pasted by the operator on 2026-07-19. Supersedes the earlier condensed
12-step plan in `PLAN.md` §13 as the acceptance bar — that 12-step list
remains useful as sequencing, but "done" is judged against this doc.

---

# 1. PRODUCT ARCHITECTURE

Create one unified top-level module:

# Trade Desk

The Trade Desk contains:

Trade Desk
├── Command Overview
├── Equity Desk
├── Options Desk
├── Copilot Queue
├── Positions
├── Orders
├── Execution Monitor
├── Trade Replay
└── Desk Settings

Do not create separate top-level sidebar entries for every scanner, order ticket, screener, or options strategy.

Tools should live inside the appropriate desk.

Use this global workflow:

Market Discovery
→ Strategy Evidence
→ Alpha Edge Signal
→ Probabilistic Scenario
→ Event and Macro Gate
→ Risk Engine
→ Portfolio Engine
→ Manual / Copilot / Autopilot Decision
→ OMS
→ Broker Adapter
→ Order State Stream
→ Position Monitoring
→ Exit Intelligence
→ Journal and Replay

No UI widget, scanner, signal, AI agent, alert, chart action, or strategy builder may bypass this workflow.

---

# 2. SIDEBAR INFORMATION ARCHITECTURE

Use the following institutional-grade sidebar:

OLBOS TRADE
TERMINAL

1. Command Center

2. Markets
   - Market Overview
   - Heatmaps
   - Watchlists
   - News & Catalysts
   - Economic Calendar
   - Earnings Calendar
   - Sector Rotation

3. Trade Desk
   - Command Overview
   - Equity Desk
   - Options Desk
   - Copilot Queue
   - Positions
   - Orders
   - Execution Monitor
   - Trade Replay

4. Strategies
   - Alpha Edge Signal
   - Signal Center
   - Strategy Cards
   - Strategy Builder
   - Strategy Health
   - Alerts

5. Portfolio & Risk
   - Portfolio Overview
   - Portfolio Heat
   - Exposure
   - Correlation Clusters
   - Stress & VaR
   - Drawdown Control
   - Risk Rules

6. Research Lab
   - Backtests
   - Walk-Forward
   - ML Models
   - Scenario Lab
   - Paper Validation
   - Research Reports

7. Performance
   - Account Performance
   - Strategy Performance
   - Attribution
   - Risk-Adjusted Metrics
   - Backtest
   - Paper
   - Limited Live
   - Live

8. Data & Integrations
   - Broker Connections
   - Market Data Providers
   - Options Data
   - News Providers
   - Data Quality
   - System Logs

9. Settings

10. Kill Switch

Requirements:

- Sidebar groups must be collapsible.
- Active route must be obvious.
- Counts and status badges may appear beside Copilot Queue, Orders, Positions, Risk, and Data.
- Kill Switch must remain fixed and visible near the bottom.
- Do not expose administrative or diagnostic tools to users without permission.
- Mobile navigation must use a drawer or compact bottom navigation.

---

# 3. TRADE DESK SHELL

Build one reusable Trade Desk shell shared by equities and options.

The shell must contain:

## Global Header

Display:

- Selected account
- Trading environment: Paper or Live
- Trading mode: Manual, Copilot, or Autopilot
- Risk profile: Conservative, Balanced, or Aggressive
- Broker connection status
- Market-data status
- Data freshness
- Buying power
- Portfolio heat
- Daily P&L
- Drawdown status
- Macro-event risk
- Kill-switch status

The Paper or Live badge must always remain visible.

Never rely only on color.

## Primary Desk Tabs

Use:

EQUITIES | OPTIONS | COPILOT | POSITIONS | ORDERS | EXECUTION | REPLAY

Tabs should update the workspace without unnecessary full-page navigation.

Preserve the selected symbol, watchlist, account, and layout when switching between related tabs.

## Workspace Layout

Use a flexible multi-panel layout:

Left Rail:
Discovery and symbol selection

Center Workspace:
Chart, chain, payoff, order construction, or replay

Right Intelligence Rail:
Signals, risk, scenario, portfolio, and eligibility

Bottom Activity Panel:
Orders, positions, fills, journal, and logs

Panels should be:

- Resizable
- Collapsible
- Persisted per user
- Responsive
- Keyboard accessible
- Resettable to default

---

# 4. COMMAND OVERVIEW

Create a Trade Desk Command Overview as the landing screen.

Show:

- Current market regime
- Volatility regime
- Macro-event risk
- Today's trading restrictions
- Alpha Edge Entry candidates
- Active Hold states
- Exit warnings
- Copilot reviews waiting
- Open positions
- Working orders
- Rejected orders
- Portfolio heat
- Risk budget remaining
- Broker health
- Data health
- Strategy health
- Current kill-switch state

Provide four primary queues:

1. Opportunities
2. Reviews Required
3. Risk Actions
4. Execution Exceptions

Examples of execution exceptions:

- Rejected order
- Partial fill
- Stale order
- Broker disconnection
- Unexpected position
- Buying-power mismatch
- Missing order acknowledgement
- Duplicate-order prevention triggered

The Command Overview must be actionable but must not become a crowded dashboard.

---

# 5. EQUITY DESK

Redesign the Equity Desk as a complete decision and execution workspace.

## 5.1 Left Discovery Rail

Include tabs for:

- Watchlists
- Alpha Edge candidates
- Market scanner
- Sector leaders
- Movers
- Alerts
- News catalysts
- Existing positions

Each symbol row may show:

- Symbol
- Price
- Percentage change
- Relative volume
- Market bias
- Entry Score
- Exit Score for held positions
- Event risk
- Strategy fit
- Portfolio overlap
- Data freshness

Allow users to filter by:

- Watchlist
- Sector
- Market capitalization
- Price
- Volume
- Relative volume
- Trend
- Market regime
- Alpha Edge state
- Event risk
- Portfolio eligibility
- Data quality

## 5.2 Center Chart Workspace

Use the existing Gold Standard Charting System.

Support:

- Candles
- Volume
- Multiple timeframes
- VWAP
- EMA and SMA
- Support and resistance
- Opening range
- Market structure
- Macro-event markers
- Earnings markers
- Alpha Edge markers
- Entry, stop, target, and exit levels
- Existing position overlay
- Saved drawings
- Trade replay

Default chart view must remain clean.

Use progressive disclosure for advanced overlays.

## 5.3 Right Intelligence Rail

Display:

### Market Intelligence

- Market bias
- Multi-timeframe alignment
- Trend state
- Relative volume
- Market regime
- Sector strength

### Alpha Edge

- Entry Score
- Hold Score
- Exit Score
- Risk Score
- Current lifecycle state
- Score trend
- Main supporting evidence
- Main deterioration evidence

### Probabilistic Intelligence

- Bullish probability
- Sideways probability
- Bearish probability
- Confidence tier
- Abstain status
- Expected range
- Model agreement

### Event Intelligence

- Earnings
- Dividends
- Macro events
- News catalyst
- Event severity
- Strategy restriction

### Portfolio Intelligence

- Existing exposure
- Symbol concentration
- Sector concentration
- Correlation cluster
- Estimated exposure after trade
- Portfolio heat after trade

### Eligibility

Show:

- Informational Only
- Manual Eligible
- Copilot Review Eligible
- Autopilot Candidate
- Blocked

Always show the exact reason when blocked.

## 5.4 Equity Order Composer

Support:

- Buy
- Sell
- Sell short only if broker/account permits
- Market
- Limit
- Stop
- Stop-limit
- Bracket
- Trailing stop
- Day
- GTC where supported
- Share quantity
- Dollar quantity
- Risk-based sizing

Display before submission:

- Estimated order value
- Estimated slippage
- Buying-power impact
- Position size after fill
- Portfolio allocation after fill
- Maximum planned loss
- Stop distance
- Reward-to-risk
- Event risk
- Data freshness

The order composer must request an eligibility decision from backend services.

The frontend must not independently decide that a trade is safe.

## 5.5 Equity Position Monitor

For every position show:

- Quantity
- Average cost
- Current price
- Unrealized P&L
- Realized P&L
- Initial thesis
- Current thesis state
- Entry Score at entry
- Current Hold Score
- Current Exit Score
- Risk Score
- Stop
- Target
- Trailing level
- Maximum favorable excursion
- Maximum adverse excursion
- Event risk
- Suggested action
- Next evaluation time

Possible actions:

- Hold
- Add eligible
- Reduce
- Tighten stop
- Exit warning
- Exit confirmed
- Mandatory risk exit

---

# 6. OPTIONS DESK

Place the Options Desk inside Trade Desk.

The Options Desk must reuse the same shell, authentication, account state, risk services, portfolio services, OMS, broker adapter, journal, and replay systems.

Do not create a separate execution engine.

Use the following internal structure:

Options Desk
├── Chain
├── Strategy Builder
├── Spread Scanner
├── Income Strategies
├── Options Flow
├── 0DTE Decision Desk
├── Position Monitor
└── Roll Manager

## 6.1 Options Discovery Rail

Include:

- Options watchlists
- Spread candidates
- Alpha Edge options candidates
- Cash-secured put candidates
- Covered-call candidates
- Wheel positions
- Options-flow alerts
- 0DTE candidates
- Earnings candidates
- Existing options positions

## 6.2 Options Center Workspace

Allow interchangeable center views:

- Underlying chart
- Options chain
- Strategy builder
- Payoff diagram
- IV term structure
- Volatility smile
- Open-interest map
- Expected move
- Flow tape
- GEX and positioning
- Trade replay

Do not show unsupported advanced data as if it exists.

Display unavailable or delayed states explicitly.

## 6.3 Options Intelligence Rail

Display:

- Strategy type
- Expiration
- DTE
- Strikes
- Bid
- Ask
- Mid
- Spread width
- Volume
- Open interest
- Delta
- Gamma
- Theta
- Vega
- IV
- IV Rank
- IV percentile
- Expected move
- Maximum profit
- Maximum loss
- Breakeven
- Probability metrics
- Assignment risk
- Exercise risk
- Earnings risk
- Dividend risk
- Portfolio Greeks impact
- Buying-power impact
- Liquidity score
- Alpha Edge scores
- Scenario compatibility
- Risk decision
- Eligibility

## 6.4 Supported Strategy Builders

Initial supported strategies:

Defined-Risk Directional:
- Bull call spread
- Bear put spread

Defined-Risk Credit:
- Bull put spread
- Bear call spread

Income:
- Cash-secured put
- Covered call
- Wheel lifecycle

Single-leg long options may be supported if already present.

Do not add naked short options unless explicitly approved and broker/account rules support them.

Do not default to iron condors unless explicitly requested.

## 6.5 Spread Scanner

Rank opportunities using:

- Strategy fit
- Expected value
- Maximum loss
- Reward-to-risk
- Probability of profit
- Bid-ask quality
- Open interest
- Volume
- DTE
- IV Rank
- Event risk
- Alpha Edge score
- Scenario compatibility
- Portfolio Greeks
- Concentration
- Data quality

Do not rank solely by premium or annualized return.

## 6.6 Income Strategies

Include:

- CSP Screener
- Covered Call Screener
- Wheel Tracker
- Assignment Risk
- Adjusted Cost Basis
- Roll Candidates
- Income Performance

## 6.7 Options Flow

Treat options flow as evidence only.

Show:

- Contract
- Strike
- Expiration
- DTE
- Call or put
- Premium
- Volume
- Open interest
- Trade-side estimate
- Repeat-flow status
- Flow Quality Score
- Alternative interpretations
- Data freshness

Do not claim institutional intent.

## 6.8 0DTE Decision Desk

Include:

- Morning playbook
- Prime trading windows
- Setup scorecard
- Expected move
- VWAP
- Opening range
- Time-to-expiration risk
- Gamma-risk warning
- Liquidity
- No-trade state
- Mandatory time exits
- Session replay

Autopilot for 0DTE must remain disabled unless separately validated and explicitly approved.

---

# 7. COPILOT QUEUE

Create one centralized Copilot Queue for equities and options.

Each review card must show:

- Symbol
- Asset type
- Strategy
- Direction
- Entry
- Stop or invalidation
- Target
- Maximum loss
- Position size
- Buying-power impact
- Portfolio impact
- Alpha Edge scores
- Scenario probabilities
- Confidence tier
- Event risk
- Data quality
- Risk Engine result
- Portfolio Engine result
- Eligibility
- Expiration time for the recommendation

Actions:

- Approve
- Reject
- Snooze
- Simulate
- Modify within permitted limits
- Add to watchlist
- Open full analysis

Any modification must trigger a new backend eligibility evaluation.

Do not reuse the original approval after material trade parameters change.

Record:

- User decision
- Timestamp
- Original recommendation
- Modified recommendation
- Final approved parameters
- Risk decision
- Portfolio decision
- Resulting order ID

---

# 8. POSITIONS WORKSPACE

Create a unified positions workspace with tabs:

- All
- Equities
- Options
- Income Strategies
- Intraday
- Swing
- Closed Today

Display:

- Current value
- P&L
- Risk
- Alpha Edge state
- Event risk
- Strategy
- Holding period
- DTE
- Greeks
- Portfolio contribution
- Suggested action
- Next review

Add portfolio-level views:

- Exposure by asset
- Sector exposure
- Correlation clusters
- Greeks
- Assignment exposure
- Concentration
- Risk contribution
- Stress scenario impact

---

# 9. ORDERS AND EXECUTION MONITOR

Separate the user-facing order list from execution diagnostics.

## Orders

Show:

- Working
- Pending approval
- Submitted
- Partially filled
- Filled
- Canceled
- Rejected
- Expired
- Replaced

## Execution Monitor

Show:

- Client order ID
- Strategy
- Submission time
- Broker acknowledgement
- Fill events
- Partial fills
- Average fill
- Expected price
- Slippage
- State transitions
- Retry activity
- Rejection reason
- Reconciliation status
- Audit link

Requirements:

- Idempotent client order IDs
- Duplicate-order protection
- Explicit state machine
- Streaming order updates where supported
- Reconciliation between internal state and broker state
- Retry logic that cannot create duplicate orders
- Clear handling of partial fills
- Clear handling of replacement and cancellation
- Stale-order detection
- Broker-disconnection recovery
- Manual intervention log

---

# 10. TRADE REPLAY

Create a unified Trade Replay workspace.

Allow users to replay:

- Signal generation
- Alpha Edge score changes
- Scenario changes
- Event context
- Risk decisions
- Portfolio decisions
- Copilot decisions
- Order lifecycle
- Fills
- Position changes
- Exit decisions
- Final outcome

Replay controls:

- Play
- Pause
- Step forward
- Step backward
- Jump to signal
- Jump to approval
- Jump to order
- Jump to fill
- Jump to exit
- Toggle chart overlays
- Toggle events
- Toggle score history

Separate:

- Backtest replay
- Walk-forward replay
- Paper replay
- Limited-live replay
- Live replay

Never combine these sources without visible labels.

---

# 11. SHARED TRADE INTENT CONTRACT

Create a broker-independent TradeIntent contract used by Equity Desk, Options Desk, Copilot, and Autopilot.

Suggested structure:

TradeIntent
- id
- account_id
- user_id
- source
- mode
- risk_profile
- asset_class
- symbol
- strategy_id
- strategy_version
- side
- quantity
- notional
- order_type
- limit_price
- stop_price
- time_in_force
- option_legs
- entry_reason
- invalidation
- target
- maximum_risk
- expected_value
- data_timestamp
- data_quality
- signal_snapshot_id
- scenario_snapshot_id
- alpha_edge_snapshot_id
- created_at
- expires_at

TradeIntentEvaluation
- trade_intent_id
- macro_gate
- event_gate
- data_gate
- strategy_gate
- liquidity_gate
- risk_gate
- portfolio_gate
- buying_power_gate
- execution_gate
- final_status
- block_reasons
- warnings
- suggested_size
- evaluated_at
- evaluation_version

Possible final statuses:

- INFORMATIONAL
- MANUAL_ELIGIBLE
- COPILOT_REVIEW_REQUIRED
- AUTOPILOT_ELIGIBLE
- BLOCKED
- EXPIRED

No frontend component may submit an order without a valid, current evaluation.

---

# 12. RISK AND PORTFOLIO AUTHORITY

Risk Engine and Portfolio Engine remain final authority.

The UI must not calculate final approval.

Hard controls may include:

- Daily loss limit
- Weekly loss limit
- Drawdown limit
- Single-position risk
- Symbol exposure
- Sector exposure
- Correlation exposure
- Options Greeks
- Assignment exposure
- Buying power
- Margin use
- Position count
- Trade frequency
- Event risk
- Liquidity
- Slippage
- Data freshness
- Broker health
- Strategy health
- Kill switch

Aggressive mode may increase permitted activity only within validated limits.

Aggressive mode must not:

- Force trades
- Disable risk controls
- Increase leverage without explicit policy
- Override event restrictions
- Ignore portfolio concentration
- Trade stale data
- Bypass the kill switch

---

# 13. UI DESIGN SYSTEM

Preserve the OlbosTrade institutional terminal identity.

Design language:

- Near-black base
- Flat panels
- Hairline separators
- Minimal shadows
- Minimal border radius
- Teal accent for actionable information
- Amber for caution
- Red for losses, blocks, and critical risk
- Green only for favorable or completed positive states
- Monospaced typography for prices, quantities, Greeks, and P&L
- Sans-serif typography for labels and explanations

Do not overuse gradients, glassmorphism, or decorative animation.

The experience should feel:

- Dense but readable
- Professional
- Fast
- Calm
- Auditable
- Risk-aware

## Responsive Behavior

Desktop:
- Four-panel workspace

Tablet:
- Collapsible discovery and intelligence rails

Mobile:
- Chart or primary module first
- Bottom-sheet intelligence
- Sticky symbol/timeframe bar
- Sticky risk/environment indicator
- Bottom action bar
- Large approve/reject controls
- No dense desktop tables

---

# 14. ACCESSIBILITY

Implement:

- Keyboard navigation
- Logical focus order
- Screen-reader labels
- High-contrast compatibility
- Reduced-motion support
- Labels in addition to color
- Tooltips for advanced metrics
- Clear disabled-state reasons
- Accessible chart summaries
- Responsive text scaling

---

# 15. FRONTEND ARCHITECTURE

Use the existing frontend stack and design system.

Suggested component boundaries:

trade-desk/
├── TradeDeskShell
├── TradeDeskHeader
├── TradeDeskTabs
├── DiscoveryRail
├── IntelligenceRail
├── ActivityPanel
├── PanelLayoutManager
├── CommandOverview
├── equity/
│   ├── EquityDesk
│   ├── EquityOrderComposer
│   ├── EquityPositionMonitor
│   └── EquityDiscovery
├── options/
│   ├── OptionsDesk
│   ├── OptionsChain
│   ├── OptionsStrategyBuilder
│   ├── SpreadScanner
│   ├── IncomeStrategyDesk
│   ├── OptionsFlowPanel
│   ├── ZeroDteDesk
│   └── OptionsPositionMonitor
├── copilot/
│   ├── CopilotQueue
│   ├── CopilotReviewCard
│   └── CopilotDecisionModal
├── orders/
│   ├── OrdersWorkspace
│   ├── OrderStateBadge
│   └── OrderDetailDrawer
├── execution/
│   ├── ExecutionMonitor
│   └── ExecutionTimeline
├── positions/
│   ├── PositionsWorkspace
│   └── PositionDetailDrawer
└── replay/
    ├── TradeReplay
    └── ReplayTimeline

Do not force these exact paths if equivalent existing modules already exist.

Reuse existing components wherever appropriate.

---

# 16. BACKEND ARCHITECTURE

Use existing backend services.

Expected responsibilities:

- Trade Intent Service
- Eligibility Evaluation Service
- Strategy Evidence Service
- Alpha Edge Service
- Scenario Service
- Event Gate
- Risk Service
- Portfolio Service
- Buying Power Service
- OMS
- Broker Adapter
- Order State Service
- Position Service
- Journal Service
- Replay Service
- Notification Service
- Audit Service

Do not create circular dependencies.

Suggested direction:

API
→ Application Services
→ Domain Services
→ Repositories and Provider Interfaces
→ External Broker / Data Providers

Risk and portfolio decisions should be backend-authoritative.

---

# 17. REAL-TIME EVENT ARCHITECTURE

Use real-time events where supported.

Potential events:

- market.quote.updated
- market.bar.closed
- signal.created
- signal.confirmed
- alpha_edge.updated
- scenario.updated
- risk.updated
- portfolio.updated
- trade_intent.created
- trade_intent.evaluated
- copilot.review.created
- copilot.review.decided
- order.submitted
- order.acknowledged
- order.partially_filled
- order.filled
- order.rejected
- order.canceled
- position.opened
- position.updated
- position.closed
- kill_switch.engaged
- provider.degraded

Requirements:

- Versioned payloads
- Event timestamps
- Correlation IDs
- Idempotent consumers
- Retry policy
- Dead-letter handling where infrastructure supports it
- Audit trail
- No duplicate execution

Do not introduce a complex event bus if the current architecture cannot support it safely.

Use the simplest reliable mechanism compatible with the existing system.

---

# 18. DATA QUALITY

Every desk must display data status.

Track:

- Provider
- Real-time or delayed
- Freshness
- Completeness
- Last update
- Missing fields
- Degraded mode
- Confidence reduction

Examples:

Options Data:
Real-Time OPRA

Flow Data:
Not Enabled

News:
Delayed Public Sources

Macro:
Current

Data Quality:
82 / 100

Block execution when required data is stale or unavailable.

---

# 19. SECURITY

Requirements:

- Server-side secrets only
- No broker keys in frontend
- Existing API authorization preserved
- Role-based permissions
- User-account isolation
- Audit logs for trade decisions
- Audit logs for configuration changes
- Secure WebSocket authentication
- Rate limiting
- Input validation
- CSRF protection where applicable
- Safe error messages
- No sensitive information in logs
- Screenshot privacy mode
- Explicit environment safeguards

Any live-trading capability must require explicit server-side configuration.

Do not infer Live mode from credentials.

---

# 20. CURSOR BUILD WORKFLOW

Cursor is responsible for focused implementation.

Do not ask Cursor to scan or rewrite the entire repository.

Use separate Cursor chats for each phase.

## Cursor Phase A — Architecture Mapping

Use:

- integration-lead
- repo-pruner
- auditor

Tasks:

1. Inspect only relevant Trade Desk, chart, strategy, risk, portfolio, OMS, broker, journal, API, and frontend paths.
2. Map existing reusable modules.
3. Identify duplicate or obsolete components.
4. Produce an implementation plan of 12 steps or fewer.
5. Do not write code yet.

## Cursor Phase B — Shared Shell

Use:

- product-ux
- test-engineer

Build:

- Trade Desk routes
- TradeDeskShell
- Header
- Tabs
- Panel layout
- Sidebar restructuring
- Responsive behavior
- Feature flags

No execution changes.

## Cursor Phase C — Equity Desk

Use:

- product-ux
- risk-architect
- test-engineer

Build:

- Discovery rail
- Chart integration
- Intelligence rail
- Order composer
- Position monitor
- Eligibility display

Use paper mode only during development.

## Cursor Phase D — Options Desk

Use:

- quant-researcher
- risk-architect
- product-ux
- test-engineer

Build:

- Chain
- Strategy builder
- Spread scanner
- Income strategy workspace
- Options position monitor
- 0DTE read-only/Copilot workspace

No new Autopilot behavior.

## Cursor Phase E — Copilot and Execution

Use:

- risk-architect
- auditor
- test-engineer

Build:

- Copilot Queue
- Review cards
- TradeIntent evaluation
- Order state monitor
- Execution timeline
- Audit logging

## Cursor Phase F — Replay and Hardening

Use:

- test-engineer
- auditor
- integration-lead

Build:

- Trade Replay
- Reconciliation
- Failure handling
- Accessibility
- Mobile behavior
- Performance optimization

---

# 21. CLAUDE CODE INTEGRATION AND DEPLOYMENT WORKFLOW

Claude Code is responsible for final integration, production hardening, and release preparation.

Claude Code must not blindly rewrite Cursor's work.

## Stage 1 — Integration Audit

Review:

- Git diff
- Architecture boundaries
- New dependencies
- Migrations
- Environment variables
- Feature flags
- API contracts
- Authentication
- Risk and portfolio paths
- Order path
- Paper/live behavior
- Frontend data exposure

Return findings before changing code.

## Stage 2 — Cross-Module Validation

Confirm:

- Equity and Options desks use the same TradeIntent contract.
- Risk Engine remains final authority.
- Portfolio Engine remains final authority.
- OMS is the only order-submission pathway.
- Broker calls remain server-side.
- Copilot modifications trigger reevaluation.
- Chart and alerts cannot directly submit orders.
- Paper/live environment is explicit.
- Kill switch is enforced.
- Order retries are idempotent.
- Performance sources remain separated.

## Stage 3 — Migration Review

Review all database migrations for:

- Backward compatibility
- Indexes
- Foreign keys
- Defaults
- Nullable transitions
- Rollback
- Large-table safety
- Existing data preservation

Do not delete historical trade, signal, order, or audit records.

## Stage 4 — Test and Build

Run the narrowest relevant tests first.

Backend:

- Unit tests
- TradeIntent tests
- Risk-gate tests
- Portfolio-gate tests
- Order-state tests
- Broker-adapter tests
- Copilot tests
- Replay tests
- Authorization tests

Frontend:

- Type checking
- Component tests
- Route tests
- Accessibility tests
- Responsive tests
- Production build

Then run the established project release commands.

Do not invent commands.

Read the current project documentation, package scripts, Docker files, and CI configuration.

## Stage 5 — Paper Environment Validation

Validate in paper mode:

- Equity order
- Options spread order
- Reject flow
- Cancel flow
- Partial-fill flow
- Stale-order flow
- Broker disconnect
- Data degradation
- Risk block
- Portfolio block
- Copilot approval
- Copilot rejection
- Kill switch
- Replay

Do not enable live trading.

## Stage 6 — Deployment Preparation

Produce:

- Release notes
- Migration instructions
- Environment-variable checklist
- Deployment commands
- Health-check instructions
- Monitoring checklist
- Rollback commands
- Known limitations
- Post-deployment smoke tests

## Stage 7 — Deployment

Deploy only using the repository's existing deployment architecture.

Preserve:

- HTTPS
- Reverse proxy
- API security
- Database backup process
- Environment separation
- Health checks
- Logging
- Monitoring
- Rollback capability

Do not deploy if:

- Tests fail
- Migrations are unsafe
- Broker mode is ambiguous
- Risk path is bypassed
- Authorization is incomplete
- Kill switch is not enforced
- Data freshness cannot be verified
- Order idempotency is unverified

---

# 22. FEATURE FLAGS

Add feature flags for:

- trade_desk_v2
- equity_desk_v2
- options_desk_v2
- copilot_queue_v2
- execution_monitor_v2
- trade_replay_v2
- zero_dte_desk
- options_flow
- alpha_edge_integration
- probabilistic_intelligence
- mobile_trade_desk

Feature flags must support gradual rollout and rollback.

Do not remove the existing Trade Desk until the new version has passed paper validation.

---

# 23. TESTING REQUIREMENTS

Add focused tests for:

## Navigation and Layout

- Sidebar grouping
- Active route
- Saved panel layout
- Responsive behavior
- Feature-flag fallback

## Trade Intent

- Valid equity intent
- Valid options intent
- Invalid parameters
- Expired intent
- Material modification requires reevaluation
- Stale evaluation cannot execute

## Risk

- Position size
- Daily loss
- Drawdown
- Concentration
- Correlation
- Event risk
- Buying power
- Data freshness
- Kill switch

## Orders

- Submission
- Acknowledgement
- Partial fill
- Fill
- Rejection
- Cancellation
- Replacement
- Expiration
- Retry
- Deduplication
- Reconciliation

## Copilot

- Approve
- Reject
- Snooze
- Modify
- Expired recommendation
- Risk status changed before approval
- Portfolio status changed before approval

## Equity Desk

- Order composer calculations
- Eligibility labels
- Position monitor
- Alpha Edge display
- Event warnings

## Options Desk

- Multi-leg validation
- Maximum profit/loss
- Breakeven
- Greeks
- Assignment risk
- Liquidity checks
- DTE restrictions
- Event restrictions
- Roll candidate logic

## Replay

- Timeline accuracy
- Event ordering
- Source labels
- Backtest/paper/live separation
- Missing-event handling

## Security

- Authorization
- Account isolation
- No frontend secrets
- WebSocket authentication
- Audit-log creation
- Live-mode protection

---

# 24. ACCEPTANCE CRITERIA

The redesign is accepted only when:

1. Equity Desk and Options Desk share one execution architecture.
2. Risk Engine and Portfolio Engine remain backend-authoritative.
3. No chart, alert, scanner, AI, or signal can directly submit an order.
4. Paper/live environment is always visible.
5. Copilot decisions are fully audited.
6. Modified trades are reevaluated.
7. Orders have idempotent state tracking.
8. Partial fills and rejected orders are clearly handled.
9. Positions display entry, hold, exit, and risk intelligence.
10. Options positions show Greeks, DTE, assignment risk, and liquidity.
11. Data freshness and provider limitations are visible.
12. Mobile workflows remain usable.
13. Accessibility checks pass.
14. Existing Trade Desk remains available behind rollback.
15. Paper-environment end-to-end tests pass.
16. Deployment and rollback instructions are complete.

**Note (Claude Code, 2026-07-19):** treat this as 16 separate phase-exit gates,
not one all-or-nothing release gate — see `PLAN.md` "Re-baseline" section for
current status per item.

---

# 25. EXPLICIT NON-GOALS

Do not implement during the first release:

- Live futures routing
- CME market data
- Prop-firm automation
- Multi-account copy trading
- Naked short options
- Automatic 0DTE Autopilot
- Social trading
- Public strategy marketplace
- Guaranteed-performance claims
- Direct LLM-to-broker execution
- Full institutional OMS replacement
- Unlicensed data redistribution
- Broad repository refactoring unrelated to Trade Desk

---

# 26. REQUIRED FIRST RESPONSE

Do not write code immediately.

First inspect the relevant repository areas and return:

1. Current Trade Desk architecture
2. Existing components to reuse
3. Existing backend services to reuse
4. Current order path
5. Current risk and portfolio path
6. Current broker-adapter path
7. Current chart architecture
8. Current options support
9. Current sidebar and routing structure
10. Missing requirements
11. Security risks
12. Migration risks
13. Maximum 12-step implementation plan
14. File-by-file Phase 1 plan
15. Test plan
16. Rollback plan
17. Exact non-goals

Do not implement until the plan is reviewed and approved.

**Note:** items 1-17 were already answered once, in `PLAN.md`, against an
earlier condensed version of this spec. See `PLAN.md`'s "Re-baseline" section
for where those answers now under- or over-state actual coverage against
*this* document.
