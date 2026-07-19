# Changelog

## Unreleased — UI/UX Phase 4: landing trust + attribution display

Frontend-only public-page honesty from `docs/ui-ux-phase1-4/PLAN.md` Phase 4.
No trading, risk, execution, sizing, or authentication logic changed. No backend
`source` field added (deferred pending operator approval).

### Changed
- **Landing Free/Pro:** both CTAs are **Open paper terminal** → `/terminal`.
  Removed personal `mailto:` Pro CTA. Capability lists match what the terminal
  actually exposes today; numeric limits labeled **(planned)** / not enforced.
- **Landing footer:** removed five disabled Privacy/Terms/… stubs; replaced with
  “Disclosures coming soon” + Sign In.
- **Landing divergence copy:** scoped to the equity scan panel (where
  `SignalDivergence` is actually wired), not a global promise.

### Known limitations
- Background scanner `/api/equity/signals` may still omit `source`; UI continues
  to show “unknown” / “Source unavailable” via `SignalAttribution` rather than
  inventing an engine name. Populating `source`/`engine` on the payload remains
  an optional backend follow-up.

## Unreleased — UI/UX Phase 3: speak human

Frontend-only glossary and polish from `docs/ui-ux-phase1-4/PLAN.md` Phase 3.
No trading, risk, execution, sizing, or authentication logic changed.

### Added
- **MetricHint** (`MetricHint.tsx`) — one-line hover glossary for Sharpe, Sortino,
  Calmar, Max DD, POP, EV, Kelly, MAE, MFE, IV Rank, Net Theta, consecutive
  losses, and related labels. Wired into Executive Summary tiles, Trade Desk
  approvals + P&L/position headers, Dashboard stats/guardrails, and Chart IV Rank.
- **Chart legend** on ChartWorkstation (SMA-20, VWAP, volume, price levels).
- **CSS loading skeleton** (`.skeleton-block` / `.skeleton-shimmer`) replacing
  bare `LOADING CHART…` text; respects `prefers-reduced-motion`.
- **`.signal-badge`** bullish/bearish/neutral classes so direction chips are not
  styled with trading-style `mode-badge` classes.

### Changed
- Dashboard **Net Theta / day** → **Net Theta (daily)**; **Consec. Loss**
  displays as **Consecutive losses** via the glossary helper.

## Unreleased — UI/UX Phase 2: first 60 seconds

Frontend-only density and wayfinding from `docs/ui-ux-phase1-4/PLAN.md` Phase 2.
No trading, risk, execution, sizing, or authentication logic changed.

### Added
- **Welcome banner** on Command Center (`WelcomeBanner.tsx`) — three steps
  (Broker → Manual mode → Signals), dismissible via `olbos.welcome.dismissed`.
- **TerminalNavContext** so pages can deep-link through the shell without
  prop-drilling.
- **Core vs Advanced nav** filter (`filterNavForDisplay`) with a sidebar
  **Show advanced** toggle (`olbos.nav.advanced`). Deep-linked advanced pages
  stay visible even when Advanced is collapsed.

### Changed
- **ExecutiveSummary** defaults to KPI cards + Portfolio Heat + a short
  Performance strip (Win Rate, Profit Factor, Max DD, Current DD). Strategy
  Health, Meta-Strategy, Capital Allocation, Stress & VaR, System Health, and
  extra ratios sit behind **Show advanced analytics**
  (`olbos.execSummary.advanced`).
- Sidebar Core defaults: Command Center, Markets (Chart + Watchlists), Trade
  Desk, Strategies → Signals, Portfolio & Risk, System → Broker. Options Desk,
  Research, Journal, Performance, and other leaves move under Advanced.

## Unreleased — UI/UX Phase 1: trust labels

Frontend-only honesty fixes from `docs/ui-ux-phase1-4/PLAN.md` Phase 1.
No trading, risk, execution, sizing, or authentication logic changed.

### Fixed
- **ChartWorkstation** no longer shows `AUTOPILOT READY` whenever the kill
  switch is off. The top strip reads the real execution mode
  (`MANUAL` / `COPILOT` / `AUTOPILOT`) and only shows `HALTED` when the kill
  switch is active.
- **ChartWorkstation** bare BUY/SELL chips (and the selected-signal cell)
  now use `SignalAttribution` instead of misusing `mode-badge`
  conservative/scalper classes. Cross-ticker `signals[0]` fallback remains
  removed.
- **“TA Trade Plan”** renamed to **Trade plan** when a scanner signal is
  present (with source when the payload provides it) or **Chart levels**
  when levels are support/resistance fallbacks. ENTRY and RESISTANCE no
  longer share the same color.
- **Sidebar Kill Switch** engages the existing `KillSwitchButton` confirm
  modal instead of navigating to the Risk page.
- **Status bar** shows the active workspace label (e.g. `MARKETS · CHART`)
  instead of a hardcoded `TRADE DESK` on every page.
- **Header execution control** is a single Manual / Copilot / Autopilot
  tri-state (same API as Trade Desk), replacing dual COPILOT/AUTOPILOT
  ON/OFF chips that hid the state machine.
- **Nav / tab labels:** Trade Desk “Orders” → **Desk signals**; “Execution
  Logs” (which opened P&L) → **P&L Breakdown**; new **Execution Log** leaf
  opens the approvals/execution-log surface; Trade Desk tab “Risk profile”
  → **Trading style**.

### Added
- Pure helpers + Vitest coverage for execution-mode display, chart
  attribution mapping, and status-bar nav labels
  (`frontend/src/utils/chartWorkstationDisplay.ts`,
  `frontend/src/utils/navLabels.ts`).

## Unreleased — Frontend trust/UX revision + public landing page

Improved presentation and visibility of existing trading, signal, and risk states.
No trading, risk, execution, or authentication logic was added or changed —
this is a frontend-only change set (see the implementation report delivered
alongside this change for the full evidence table).

### Added
- **Signal attribution** (`frontend/src/components/SignalAttribution.tsx`,
  `frontend/src/types/signal.ts`): a shared component that replaces bare
  BUY/SELL/HOLD badges with direction + source + timeframe + confidence +
  freshness + execution authority, using explicit "unknown"/"unavailable"
  wording for anything the frontend can't verify instead of omitting it.
  Wired into `EquitySignals.tsx`, `OptionsScanPanel.tsx`,
  `EquityScanPanel.tsx`, and the Copilot approvals queue in `TradeDesk.tsx`.
- **Signal divergence disclosure** (`frontend/src/components/SignalDivergence.tsx`):
  a reusable component that surfaces disagreement between two independently
  sourced signals for the same symbol (direction conflict, mixed
  confirmation, or timeframe disagreement) instead of resolving it visually.
  Never claims which signal is execution-authoritative unless that is
  already known from the data.
- **Persistent capital-at-risk status bar**
  (`frontend/src/components/GlobalRiskStatus.tsx`), mounted in
  `TerminalLayout.tsx` above the main content on every authenticated page.
  Shows live/paper environment, AUTOPILOT state, kill-switch state, daily
  drawdown, and remaining daily risk budget (derived only when both the
  current loss and the loss limit are available from the same verified
  source, in the same unit). Every field independently renders
  loading/available/unavailable/unknown — a failed or missing read is never
  displayed as a value that looks safe.
- **Public landing page** (`frontend/src/pages/Landing.tsx`,
  `frontend/src/landing.css`), mounted at `/` via `react-router-dom` (an
  existing, previously-unused dependency). The terminal is unchanged and now
  lives at `/terminal/*`; an unmatched route redirects to `/`. All copy is
  grounded in repository evidence (README, TRADING_POLICY.md,
  ARCHITECTURE_MEMO.md); every performance figure is explicitly labeled as
  unpublished/placeholder, and no guaranteed-return language is used.
- Route-level code splitting (`React.lazy`) for the landing page and the
  terminal bundle, so visiting either surface no longer downloads the other.
- Reduced-motion support: the ticker marquee and status-dot pulse animation
  now respect `prefers-reduced-motion`.
- Minimal test tooling (Vitest + Testing Library — new devDependencies, none
  existed before) and unit tests for `SignalAttribution`, `SignalDivergence`,
  `GlobalRiskStatus`, and `Landing`.

### Changed
- `TerminalLayout.tsx`: mounts `GlobalRiskStatus` between the ticker strip
  and the main content area; marquee marked for reduced-motion.
- `EquitySignals.tsx`, `OptionsScanPanel.tsx`, `EquityScanPanel.tsx`,
  `TradeDesk.tsx`: bare directional badges replaced with
  `SignalAttribution`.
- `index.tsx`: now renders a `BrowserRouter` with lazy-loaded `/` and
  `/terminal/*` routes instead of mounting `App` directly.

### Fixed
- **Terminal-wide crash on bad market data.** Found by running the frontend
  against a real, locally-provisioned backend instead of only a stopped one:
  `/api/market/snapshot/{symbol}` and `/api/market/regime` both omit their
  normal fields on error (a documented yfinance-failure condition, see
  `AUDIT_2026-06.md`), and the ticker strip called `.toFixed()` /
  `.includes()` / `.replace()` on the resulting `undefined` with no error
  boundary above it — blanking the *entire* terminal, not just the ticker.
  Fixed the two unsafe field checks and wrapped the ticker strip, risk-status
  bar, sidebar, and page content each in the existing `ErrorBoundary`
  component so one panel failing can no longer take the others down.
  Regression tests added.

### Known limitations
- This repository has no authentication system (confirmed by direct
  inspection — no router, no session/token handling, a hardcoded account
  name in the sidebar). The `/` vs `/terminal` split is a navigational
  separation only; it does not gate access. Production currently gates the
  *entire* app (including any new public route) behind HTTP Basic Auth at
  the nginx layer when `DASH_USER`/`DASH_PASS` are set
  (`frontend/docker-entrypoint.sh`) — making the landing page genuinely
  public in that deployment requires an infra change (exempting `/` from
  `auth_basic`) that is out of scope here.
- No live example of two reachable, simultaneously-visible panels showing
  opposing signals for the same symbol was found in the current codebase to
  wire `SignalDivergence` into directly; it ships as a tested, ready-to-use
  component for the first place that need arises.
- New devDependencies (`vitest`, `@testing-library/*`, `jsdom`) pull in
  `esbuild <=0.24.2`, flagged by `npm audit` for a dev-server-only
  vulnerability (GHSA-67mh-4wv8-2f99) that does not affect production
  builds or runtime code.
