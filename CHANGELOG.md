# Changelog

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
