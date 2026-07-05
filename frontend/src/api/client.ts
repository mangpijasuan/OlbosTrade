/**
 * Central API client for the options trading platform backend.
 * All fetch calls go through this module — never fetch directly in components.
 */

// When running via Vite dev server (Docker or local), use "" so fetch calls
// go to /api/... — Vite's proxy forwards them to the backend container.
// Set VITE_API_URL only if you need to bypass the proxy (e.g. direct calls from a static build).
const BASE_URL = "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json();
}

// ── Health ────────────────────────────────────────────────────────────────────
export const api = {
  health: () => request<{ status: string }>("/health"),

  // ── Backtest ──────────────────────────────────────────────────────────────
  runBacktest: (body: object) => request("/api/backtest/run", { method: "POST", body: JSON.stringify(body) }),
  getBacktestResults: (id: string) => request(`/api/backtest/${id}/results`),
  getBacktestHistory: (limit?: number) =>
    request(`/api/backtest/history${limit ? `?limit=${limit}` : ""}`),
  compareStrategies: (body: object) => request("/api/backtest/compare", { method: "POST", body: JSON.stringify(body) }),

  // ── Market Data ───────────────────────────────────────────────────────────
  getSnapshot: (symbol: string) => request(`/api/market/snapshot/${symbol}`),
  getRegime: () => request("/api/market/regime"),
  getOptionsChain: (symbol: string, expiry: string) => request(`/api/market/options-chain/${symbol}?expiry=${expiry}`),
  getIVRank: (symbol: string) => request(`/api/market/iv-rank/${symbol}`),

  // ── Paper Trading ─────────────────────────────────────────────────────────
  getPositions: () => request("/api/paper-trade/positions"),
  getPortfolio: () => request("/api/paper-trade/portfolio"),
  toggleStrategy: (strategy: string) => request(`/api/paper-trade/toggle/${strategy}`, { method: "POST" }),
  getTradeHistory: (params?: { limit?: number; status?: string }) => {
    const q = new URLSearchParams();
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.status) q.set("status", params.status);
    const qs = q.toString();
    return request(`/api/paper-trade/history${qs ? `?${qs}` : ""}`);
  },
  getGreeksSummary: () => request("/api/paper-trade/greeks-summary"),

  // ── Risk ──────────────────────────────────────────────────────────────────
  getPortfolioState: () => request("/api/risk/portfolio-state"),
  getTradeApproval: (tradeId: string) => request(`/api/risk/approval/${tradeId}`),
  getDailyPnl: () => request("/api/risk/daily-pnl"),
  getLatestReconciliation: () => request("/api/risk/reconciliation/latest"),
  getReconciliationHistory: (limit?: number) =>
    request(`/api/risk/reconciliation/history${limit ? `?limit=${limit}` : ""}`),
  runReconciliation: () => request("/api/risk/reconciliation/run", { method: "POST" }),
  getKillSwitchStatus: () => request("/api/risk/kill-switch/status"),
  triggerKillSwitch: () => request("/api/risk/kill-switch/trigger", { method: "POST" }),

  // ── Options Income (Wheel & CSP) ──────────────────────────────────────────
  screenCsp: (body: object) =>
    request("/api/options/csp/screen", { method: "POST", body: JSON.stringify(body) }),

  // ── Intelligence Hub ──────────────────────────────────────────────────────
  getCatalystCalendar: (symbols?: string, daysAhead = 45) =>
    request(`/api/intel/calendar?days_ahead=${daysAhead}${symbols ? `&symbols=${symbols}` : ""}`),
  getWatchlists: () => request("/api/intel/watchlists"),
  getDataQuality: (symbol: string) => request(`/api/intel/data-quality/${symbol}`),
  getWhyMoving: (symbol: string) => request(`/api/intel/why-moving/${symbol}`),
  getSymbolNews: (symbol: string, limit = 15) => request(`/api/intel/news/${symbol}?limit=${limit}`),
  getSymbolFilings: (symbol: string, limit = 15) => request(`/api/intel/filings/${symbol}?limit=${limit}`),
  getClassifiedNews: (symbol: string, limit = 15) => request(`/api/intel/classify/${symbol}?limit=${limit}`),
  getInsiderIntel: (symbol: string) => request(`/api/intel/insider/${symbol}`),

  // ── Chart Intelligence ────────────────────────────────────────────────────
  getMarketBias: (symbol: string, strategy = "default") => request(`/api/chart/bias/${symbol}?strategy=${strategy}`),
  getTimeframeAlignment: (symbol: string, strategy = "default") => request(`/api/chart/alignment/${symbol}?strategy=${strategy}`),
  getConfirmation: (symbol: string, strategy = "default") => request(`/api/chart/confirmation/${symbol}?strategy=${strategy}`),
  getSetupScanner: (watchlist?: string, strategy = "default") =>
    request(`/api/chart/scanner?strategy=${strategy}${watchlist ? `&watchlist=${watchlist}` : ""}`),

  // ── Smart Alerts + Notifications ──────────────────────────────────────────
  getAlertRules: () => request("/api/alerts/rules"),
  createAlertRule: (body: object) => request("/api/alerts/rules", { method: "POST", body: JSON.stringify(body) }),
  deleteAlertRule: (id: string) => request(`/api/alerts/rules/${id}`, { method: "DELETE" }),
  toggleAlertRule: (id: string, enabled: boolean) => request(`/api/alerts/rules/${id}/toggle?enabled=${enabled}`, { method: "POST" }),
  getNotifications: (unreadOnly = false) => request(`/api/notifications?unread_only=${unreadOnly}`),
  getUnreadCount: () => request("/api/notifications/unread-count"),
  markNotificationRead: (id: string) => request(`/api/notifications/${id}/read`, { method: "POST" }),
  markAllNotificationsRead: () => request("/api/notifications/read-all", { method: "POST" }),

  // ── Guardrails ────────────────────────────────────────────────────────────
  getGuardrailStatus: () => request("/api/guardrails/status"),
  getGuardrailHistory: () => request("/api/guardrails/history"),
  getTradingMode: () => request("/api/guardrails/trading-mode"),

  // ── Strategy & Signals ────────────────────────────────────────────────────
  getStrategyRegistry: () => request("/api/strategy/registry"),
  getStrategyProfile: (strategyId: string) => request(`/api/strategy/registry/${strategyId}`),
  getStrategyPresets: (strategyId?: string) =>
    request(`/api/strategy${strategyId ? `/${strategyId}/presets` : "/presets"}`),
  getStrategySnapshots: (strategyId: string) => request(`/api/strategy/${strategyId}/snapshots`),
  createStrategySnapshot: (body: object) => request("/api/strategy/snapshots", { method: "POST", body: JSON.stringify(body) }),
  restoreStrategySnapshot: (snapshotId: string) => request(`/api/strategy/snapshots/${snapshotId}/restore`, { method: "POST" }),
  compareStrategySnapshots: (left: string, right: string) =>
    request(`/api/strategy/snapshots/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`),
  getStrategyConfig: () => request("/api/strategy/config"),
  updateStrategyConfig: (body: object) => request("/api/strategy/config", { method: "PUT", body: JSON.stringify(body) }),
  getCurrentSignals: () => request("/api/strategy/signals/current"),
  getSignalExplanation: (id: string) => request(`/api/strategy/signals/${id}/explanation`),

  // ── Equity Workstation ────────────────────────────────────────────────────
  scanEquitySignals: () => request("/api/equity/scan", { method: "POST" }),
  getEquitySignals: (limit?: number) => request(`/api/equity/signals${limit ? `?limit=${limit}` : ""}`),
  getEquityChart: (symbol: string, params?: { timeframe?: string; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.timeframe) search.set("timeframe", params.timeframe);
    if (params?.limit) search.set("limit", String(params.limit));
    const q = search.toString();
    return request(`/api/equity/chart/${symbol}${q ? `?${q}` : ""}`);
  },

  // ── Research ──────────────────────────────────────────────────────────────
  getComparison: () => request("/api/research/comparison"),
  runComparison: (body: object) => request("/api/research/run-comparison", { method: "POST", body: JSON.stringify(body) }),
  getModelPerformance: () => request("/api/research/model-performance"),

  // ── Journal ───────────────────────────────────────────────────────────────
  createJournalEntry: (body: object) => request("/api/journal/entry", { method: "POST", body: JSON.stringify(body) }),
  getJournalEntries: () => request("/api/journal/entries"),
  getJournalEntry: (tradeId: string) => request(`/api/journal/${tradeId}`),
  updateJournalEntry: (id: string, body: object) => request(`/api/journal/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  getTagPerformance: () => request("/api/journal/analytics/tags"),
  getMistakeFrequency: () => request("/api/journal/analytics/mistakes"),
  getRuleBreachImpact: () => request("/api/journal/analytics/rule-breach-impact"),
  getMonthlyReview: (month: string) => request(`/api/journal/review/monthly/${month}`),

  // ── Trading Mode ────────────────────────────────────────────────────────────
  getCurrentMode:   () => request("/api/mode/current"),
  getAllModes:       () => request("/api/mode/all"),
  setTradingMode:   (body: { mode: string; confirmed: boolean }) =>
    request("/api/mode/set", { method: "POST", body: JSON.stringify(body) }),
  resetToBalanced:  () => request("/api/mode/reset-to-balanced", { method: "POST" }),

  // ── Trade Desk (Execution Modes) ───────────────────────────────────────────
  getExecutionMode:   () => request("/api/trade-desk/execution-mode"),
  setExecutionMode:   (mode: string) =>
    request("/api/trade-desk/execution-mode", { method: "POST", body: JSON.stringify({ mode }) }),
  getTradeDeskKillSwitch: () => request("/api/trade-desk/kill-switch"),
  setTradeDeskKillSwitch: (engaged: boolean) =>
    request("/api/trade-desk/kill-switch", { method: "POST", body: JSON.stringify({ engaged }) }),
  getPendingApprovals: () => request("/api/trade-desk/pending"),
  approveSignal:       (id: string) =>
    request(`/api/trade-desk/approve/${id}`, { method: "POST" }),
  rejectSignal:        (id: string) =>
    request(`/api/trade-desk/reject/${id}`, { method: "POST" }),
  getExecutionLog:     () => request("/api/trade-desk/execution-log"),

  // ── Mode Analytics ──────────────────────────────────────────────────────────
  getModeAnalytics: (params?: { date_from?: string; date_to?: string }) => {
    const q = params ? "?" + new URLSearchParams(params as any).toString() : "";
    return request(`/api/analytics/by-mode${q}`);
  },
  getModeDetail:         (mode: string) => request(`/api/analytics/mode/${mode}`),
  getSignalScoreImpact:  ()             => request("/api/analytics/signal-score-impact"),

  // ── Options Flow (Options Intelligence module) ──────────────────────────────
  getOptionsFlow: (params?: Record<string, string | number | undefined>) => {
    const clean = Object.fromEntries(
      Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== "")
    ) as Record<string, string>;
    const q = Object.keys(clean).length ? "?" + new URLSearchParams(clean).toString() : "";
    return request<{ count: number; results: any[] }>(`/api/options-flow${q}`);
  },
  getOptionsFlowSummary: () => request<any>("/api/options-flow/summary"),
};

/** Build the absolute WebSocket URL for the options-flow live stream. */
export function optionsFlowWsUrl(params?: Record<string, string | number | undefined>): string {
  const clean = Object.fromEntries(
    Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== "")
  ) as Record<string, string>;
  const q = Object.keys(clean).length ? "?" + new URLSearchParams(clean).toString() : "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/options-flow/ws${q}`;
}
