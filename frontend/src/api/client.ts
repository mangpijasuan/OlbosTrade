/**
 * Central API client for the options trading platform backend.
 * All fetch calls go through this module — never fetch directly in components.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

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

  // ── Risk ──────────────────────────────────────────────────────────────────
  getPortfolioState: () => request("/api/risk/portfolio-state"),
  getTradeApproval: (tradeId: string) => request(`/api/risk/approval/${tradeId}`),
  getDailyPnl: () => request("/api/risk/daily-pnl"),
  getKillSwitchStatus: () => request("/api/risk/kill-switch/status"),
  triggerKillSwitch: () => request("/api/risk/kill-switch/trigger", { method: "POST" }),

  // ── Guardrails ────────────────────────────────────────────────────────────
  getGuardrailStatus: () => request("/api/guardrails/status"),
  getGuardrailHistory: () => request("/api/guardrails/history"),
  getTradingMode: () => request("/api/guardrails/trading-mode"),

  // ── Strategy & Signals ────────────────────────────────────────────────────
  getStrategyConfig: () => request("/api/strategy/config"),
  updateStrategyConfig: (body: object) => request("/api/strategy/config", { method: "PUT", body: JSON.stringify(body) }),
  getCurrentSignals: () => request("/api/strategy/signals/current"),
  getSignalExplanation: (id: string) => request(`/api/strategy/signals/${id}/explanation`),

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

  // ── Mode Analytics ──────────────────────────────────────────────────────────
  getModeAnalytics: (params?: { date_from?: string; date_to?: string }) => {
    const q = params ? "?" + new URLSearchParams(params as any).toString() : "";
    return request(`/api/analytics/by-mode${q}`);
  },
  getModeDetail:         (mode: string) => request(`/api/analytics/mode/${mode}`),
  getSignalScoreImpact:  ()             => request("/api/analytics/signal-score-impact"),
};
