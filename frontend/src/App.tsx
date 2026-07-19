import React, { useState } from "react";
import "./index.css";
import TerminalLayout  from "./components/TerminalLayout";
import Dashboard       from "./pages/Dashboard";
import TradeDesk       from "./pages/TradeDesk";
import TradeDeskV2     from "./pages/TradeDeskV2";
import Journal         from "./pages/Journal";
import ModeAnalytics   from "./pages/ModeAnalytics";
// Consolidated hubs (each folds two former pages behind tabs)
import RiskCenter      from "./pages/RiskCenter";          // Risk Monitor + Guardrails
import SignalsCenter   from "./pages/SignalsCenter";       // Equity Signals + Strategy
import ResearchCenter  from "./pages/ResearchCenter";      // Research Lab: Strategy Lab + Market/Regime + Chart + Intel
import BacktestCenter  from "./pages/BacktestCenter";      // Backtest + Symphony
import ScanCenter      from "./pages/ScanCenter";           // Options + Equity EV scan engines
import OptionsFlow     from "./pages/OptionsFlow";           // Options flow (grouped-nav sub-item)
import OptionsChain    from "./pages/options/OptionsChain";  // Live calls/puts for a symbol
import IncomeStrategiesCenter from "./pages/options/IncomeStrategiesCenter";
import SystemCenter    from "./pages/SystemCenter";
import StrategyBuilder from "./pages/strategies/StrategyBuilder"; // Configure + register a strategy experiment
import Alerts          from "./pages/strategies/Alerts";     // Smart Alert rules + notifications
// Markets module
import Heatmap         from "./pages/markets/Heatmap";
import Watchlists      from "./pages/markets/Watchlists";
import ChartWorkstation from "./pages/ChartWorkstation";     // Price-action / market-structure chart
import NewsEventsCenter from "./pages/markets/NewsEventsCenter";
import { isTradeDeskV2Enabled } from "./trade-desk/featureFlags";

function UnknownPage() {
  return (
    <div style={{
      height: "100%", display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", gap: 8,
      color: "var(--ink-faint)", fontFamily: "var(--mono)",
    }}>
      <div style={{ fontSize: 13, letterSpacing: "0.08em", textTransform: "uppercase" }}>Page unavailable</div>
      <div style={{ fontSize: 11, color: "var(--ink-dim)" }}>Return to Command Center or select another workspace.</div>
    </div>
  );
}

function tradeDeskPages(v2: boolean): Record<string, React.ComponentType> {
  if (!v2) {
    return {
      paper: TradeDesk,
      "trade:copilot":   () => <TradeDesk initialTab="approvals" />,
      "trade:orders":    () => <TradeDesk initialTab="signals" />,
      "trade:positions": () => <TradeDesk initialTab="positions" />,
      "trade:logs":      () => <TradeDesk initialTab="pnl" />,
      "trade:execlog":   () => <TradeDesk initialTab="approvals" />,
    };
  }
  return {
    paper: () => <TradeDeskV2 initialTab="trade:overview" />,
    "trade:overview":  () => <TradeDeskV2 initialTab="trade:overview" />,
    "trade:equity":    () => <TradeDeskV2 initialTab="trade:equity" />,
    "trade:options":   () => <TradeDeskV2 initialTab="trade:options" />,
    "trade:copilot":   () => <TradeDeskV2 initialTab="trade:copilot" />,
    "trade:positions": () => <TradeDeskV2 initialTab="trade:positions" />,
    "trade:orders":    () => <TradeDeskV2 initialTab="trade:orders" />,
    "trade:execlog":   () => <TradeDeskV2 initialTab="trade:execlog" />,
    "trade:replay":    () => <TradeDeskV2 initialTab="trade:replay" />,
    "trade:settings":  () => <TradeDeskV2 initialTab="trade:settings" />,
    // Legacy deep-links → overview or closest v2 tab
    "trade:logs":      () => <TradeDeskV2 initialTab="trade:overview" />,
  };
}

const BASE_PAGES: Record<string, React.ComponentType> = {
  dashboard: Dashboard,
  equity:    SignalsCenter,
  backtest:  BacktestCenter,
  lab:       ResearchCenter,
  risk:      RiskCenter,
  journal:   Journal,
  analytics: ModeAnalytics,
  scan:      ScanCenter,
  settings:  SystemCenter,

  "strat:cards":     () => <SignalsCenter initialTab="strategies" />,
  "strat:builder":   StrategyBuilder,
  "strat:alerts":    Alerts,
  "options:chain":   OptionsChain,
  "options:income":  IncomeStrategiesCenter,
  "options:flow":    OptionsFlow,
  "risk:heat":       () => <RiskCenter initialTab="monitor" />,
  "risk:rules":      () => <RiskCenter initialTab="guardrails" />,
  "lab:scenario":    () => <ResearchCenter initialTab="scenario" />,
  "lab:strategy":    () => <ResearchCenter initialTab="lab" />,
  "lab:market":      () => <ResearchCenter initialTab="market" />,
  "lab:intel":       () => <ResearchCenter initialTab="intel" />,
  "lab:models":      () => <ResearchCenter initialTab="models" />,

  "markets:heatmaps":   Heatmap,
  "markets:watchlists": Watchlists,
  "markets:chart":      ChartWorkstation,
  "markets:news":       NewsEventsCenter,

  "system:broker":  () => <SystemCenter initialTab="broker" />,
  "system:market":  () => <SystemCenter initialTab="market" />,
  "system:quality": () => <SystemCenter initialTab="quality" />,
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const v2 = isTradeDeskV2Enabled();
  const PAGES = { ...BASE_PAGES, ...tradeDeskPages(v2) };
  const Page = PAGES[page] || UnknownPage;

  return (
    <TerminalLayout activePage={page} onNav={setPage}>
      <Page />
    </TerminalLayout>
  );
}
