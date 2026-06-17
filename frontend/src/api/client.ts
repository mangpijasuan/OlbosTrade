/**
 * Central API client for the options trading platform backend.
 * All fetch calls go through this module — never fetch directly in components.
 */

// When running via Vite dev server (Docker or local), use "" so fetch calls
// go to /api/... — Vite's proxy forwards them to the backend container.
// Set VITE_API_URL only if you need to bypass the proxy (e.g. direct calls from a static build).
const BASE_URL = import.meta.env.VITE_API_URL || "";
const ADMIN_API_KEY = import.meta.env.VITE_ADMIN_API_KEY || "";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function parseResponseBody(res: Response): Promise<any> {
  const contentType = res.headers.get("content-type") || "";
  if (res.status === 204) return null;
  if (contentType.includes("application/json")) return res.json();
  return res.text();
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = (options?.method || "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };
  if (ADMIN_API_KEY && MUTATING_METHODS.has(method)) {
    headers["X-Api-Key"] = ADMIN_API_KEY;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });
  const body = await parseResponseBody(res);
  if (!res.ok) {
    const detail = typeof body === "object" && body !== null
      ? body.detail || body.message || JSON.stringify(body)
      : body;
    throw new Error(`API error ${res.status}: ${detail || res.statusText}`);
  }
  return body as T;
}

// ── Health ────────────────────────────────────────────────────────────────────
export const api = {
  health: () => request<{ status: string }>("/health"),

  // ── Backtest ──────────────────────────────────────────────────────────────
  runBacktest: (body: object) => request("/api/backtest/run", { method: "POST", body: JSON.stringify(body) }),
  getBacktestResults: (id: string) => request(`/api/backtest/${id}/results`),
  getBacktestHistory: () => request("/api/backtest/history"),
  compareStrategies: (body: object) => request("/api/backtest/compare", { method: "POST", body: JSON.stringify(body) }),

  // ── Market Data ───────────────────────────────────────────────────────────
  getSnapshot: (symbol: string) => request(`/api/market/snapshot/${symbol}`),
  getOptionsChain: (symbol: string, expiry: string) => request(`/api/market/options-chain/${symbol}?expiry=${expiry}`),
  getIVRank: (symbol: string) => request(`/api/market/iv-rank/${symbol}`),

  // ── Paper Trading ─────────────────────────────────────────────────────────
  getPositions: () => request("/api/paper-trade/positions"),
  getPortfolio: () => request("/api/paper-trade/portfolio"),
  toggleStrategy: (strategy: string) => request(`/api/paper-trade/toggle/${strategy}`, { method: "POST" }),
  getTradeHistory: () => request("/api/paper-trade/history"),
  getGreeksSummary: () => request("/api/paper-trade/greeks-summary"),
  runSignalCycle: () => request("/api/paper-trade/run-cycle", { method: "POST" }),

  // ── Risk ──────────────────────────────────────────────────────────────────
  getPortfolioState: () => request("/api/risk/portfolio-state"),
  getTradeApproval: (tradeId: string) => request(`/api/risk/approval/${tradeId}`),
  getDailyPnl: () => request("/api/risk/daily-pnl"),
  getKillSwitchStatus: () => request("/api/risk/kill-switch/status"),
  triggerKillSwitch: (reason = "manual") =>
    request(`/api/risk/kill-switch/trigger?reason=${encodeURIComponent(reason)}`, { method: "POST" }),

  // ── Guardrails ────────────────────────────────────────────────────────────
  getGuardrailStatus: () => request("/api/guardrails/status"),
  getGuardrailHistory: () => request("/api/guardrails/history"),
  getTradingMode: () => request("/api/guardrails/trading-mode"),

  // ── Strategy & Signals ────────────────────────────────────────────────────
  getStrategyConfig: () => request("/api/strategy/config"),
  updateStrategyConfig: (body: object) => request("/api/strategy/config", { method: "PUT", body: JSON.stringify(body) }),
  getCurrentSignals: () => request("/api/strategy/signals/current"),
  getSignalExplanation: (id: string) => request(`/api/strategy/signals/${id}/explanation`),

  // ── Equity Signals ────────────────────────────────────────────────────────
  getEquitySignals: () => request("/api/equity/signals"),
  scanEquitySignals: () => request("/api/equity/scan", { method: "POST" }),

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
