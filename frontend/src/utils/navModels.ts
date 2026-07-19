/**
 * Sidebar nav models — legacy vs Trade Desk 2.0 (Options under Trade Desk).
 */

import type { NavGroup } from "./navLabels";

/** Pre–Trade Desk 2.0 sidebar (rollback when trade_desk_v2 is off). */
export const NAV_MODEL_LEGACY: NavGroup[] = [
  { id: "dashboard", label: "Command Center", icon: "dashboard", key: "dashboard" },
  { id: "markets",   label: "Markets",        icon: "markets", children: [
    { key: "markets:chart",      label: "Chart" },
    { key: "markets:watchlists", label: "Watchlists" },
    { key: "markets:heatmaps",   label: "Heatmaps", advanced: true },
    { key: "markets:news",       label: "News & Events", advanced: true },
  ]},
  { id: "trade", label: "Trade Desk", icon: "paper", children: [
    { key: "trade:copilot",   label: "Copilot Review" },
    { key: "trade:orders",    label: "Desk signals" },
    { key: "trade:positions", label: "Positions" },
    { key: "trade:logs",      label: "P&L Breakdown" },
    { key: "trade:execlog",   label: "Execution Log" },
  ]},
  { id: "strat", label: "Strategies", icon: "strategy", children: [
    { key: "equity",        label: "Signals" },
    { key: "strat:cards",   label: "Strategy Cards", advanced: true },
    { key: "strat:builder", label: "Strategy Builder", advanced: true },
    { key: "strat:alerts",  label: "Alerts", advanced: true },
  ]},
  { id: "options", label: "Options Desk", icon: "flow", advanced: true, children: [
    { key: "options:chain",  label: "Options Chain" },
    { key: "scan",           label: "Spread Scanner" },
    { key: "options:income", label: "Income Strategies" },
    { key: "options:flow",   label: "Options Flow" },
  ]},
  { id: "risk", label: "Portfolio & Risk", icon: "risk", key: "risk", children: [
    { key: "risk:heat",     label: "Risk Overview" },
    { key: "risk:rules",    label: "Risk Rules" },
  ]},
  { id: "lab", label: "Research", icon: "lab", advanced: true, children: [
    { key: "lab:scenario",   label: "Scenario Lab" },
    { key: "lab:strategy",   label: "Strategy Research" },
    { key: "lab:market",     label: "Market & Regime" },
    { key: "lab:models",     label: "Model Health" },
    { key: "lab:intel",      label: "Intelligence" },
    { key: "backtest",       label: "Backtests" },
  ]},
  { id: "journal",   label: "Journal & Replay", icon: "journal",   key: "journal", advanced: true },
  { id: "analytics", label: "Performance",      icon: "analytics", key: "analytics", advanced: true },
  { id: "system", label: "System", icon: "data", children: [
    { key: "system:broker",  label: "Broker" },
    { key: "system:market",  label: "Market Data", advanced: true },
    { key: "system:quality", label: "Data Quality", advanced: true },
  ]},
];

/**
 * Trade Desk 2.0 IA — Options tools remain reachable under Strategies (advanced)
 * until Phase D moves them into the Options Desk workspace. Trade Desk group
 * hosts Command Overview + desk tabs.
 */
export const NAV_MODEL_V2: NavGroup[] = [
  { id: "dashboard", label: "Command Center", icon: "dashboard", key: "dashboard" },
  { id: "markets",   label: "Markets",        icon: "markets", children: [
    { key: "markets:chart",      label: "Chart" },
    { key: "markets:watchlists", label: "Watchlists" },
    { key: "markets:heatmaps",   label: "Heatmaps", advanced: true },
    { key: "markets:news",       label: "News & Events", advanced: true },
  ]},
  { id: "trade", label: "Trade Desk", icon: "paper", children: [
    { key: "trade:overview",  label: "Command Overview" },
    { key: "trade:equity",    label: "Equity Desk" },
    { key: "trade:options",   label: "Options Desk" },
    { key: "trade:copilot",   label: "Copilot Queue" },
    { key: "trade:positions", label: "Positions" },
    { key: "trade:orders",    label: "Orders" },
    { key: "trade:execlog",   label: "Execution Monitor" },
    { key: "trade:replay",    label: "Trade Replay" },
    { key: "trade:settings",  label: "Desk Settings" },
  ]},
  { id: "strat", label: "Strategies", icon: "strategy", children: [
    { key: "equity",        label: "Signal Center" },
    { key: "strat:cards",   label: "Strategy Cards", advanced: true },
    { key: "strat:builder", label: "Strategy Builder", advanced: true },
    { key: "strat:alerts",  label: "Alerts", advanced: true },
    { key: "options:chain",  label: "Options Chain", advanced: true },
    { key: "scan",           label: "Spread Scanner", advanced: true },
    { key: "options:income", label: "Income Strategies", advanced: true },
    { key: "options:flow",   label: "Options Flow", advanced: true },
  ]},
  { id: "risk", label: "Portfolio & Risk", icon: "risk", key: "risk", children: [
    { key: "risk:heat",     label: "Risk Overview" },
    { key: "risk:rules",    label: "Risk Rules" },
  ]},
  { id: "lab", label: "Research", icon: "lab", advanced: true, children: [
    { key: "lab:scenario",   label: "Scenario Lab" },
    { key: "lab:strategy",   label: "Strategy Research" },
    { key: "lab:market",     label: "Market & Regime" },
    { key: "lab:models",     label: "Model Health" },
    { key: "lab:intel",      label: "Intelligence" },
    { key: "backtest",       label: "Backtests" },
  ]},
  { id: "journal",   label: "Journal",     icon: "journal",   key: "journal", advanced: true },
  { id: "analytics", label: "Performance", icon: "analytics", key: "analytics", advanced: true },
  { id: "system", label: "Data & Integrations", icon: "data", children: [
    { key: "system:broker",  label: "Broker Connections" },
    { key: "system:market",  label: "Market Data", advanced: true },
    { key: "system:quality", label: "Data Quality", advanced: true },
  ]},
];

export function groupIdForKey(key: string, model: NavGroup[]): string | null {
  for (const g of model) {
    if (g.key === key) return g.id;
    if (g.children?.some((c) => c.key === key)) return g.id;
  }
  return null;
}
