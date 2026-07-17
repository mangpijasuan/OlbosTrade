import React, { useState } from "react";
import "./index.css";
import TerminalLayout  from "./components/TerminalLayout";
import Dashboard       from "./pages/Dashboard";
import TradeDesk       from "./pages/TradeDesk";
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
// Data & Integrations module

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

const PAGES: Record<string, React.ComponentType> = {
  dashboard: Dashboard,
  paper:     TradeDesk,
  equity:    SignalsCenter,
  backtest:  BacktestCenter,
  lab:       ResearchCenter,
  risk:      RiskCenter,
  journal:   Journal,
  analytics: ModeAnalytics,
  csp:       IncomeStrategiesCenter,
  scan:      ScanCenter,
  settings:  SystemCenter,

  // Grouped-nav aliases → existing pages, deep-linked to the relevant tab so
  // each sub-item lands on its own view instead of a shared default.
  "trade:copilot":   () => <TradeDesk initialTab="approvals" />,
  "trade:orders":    () => <TradeDesk initialTab="signals" />,
  "trade:positions": () => <TradeDesk initialTab="positions" />,
  "trade:logs":      () => <TradeDesk initialTab="pnl" />,
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

  // Markets module
  "markets:heatmaps":   Heatmap,
  "markets:watchlists": Watchlists,
  "markets:chart":      ChartWorkstation,
  "markets:news":       NewsEventsCenter,

  // Data & Integrations module
  "system:broker":  () => <SystemCenter initialTab="broker" />,
  "system:market":  () => <SystemCenter initialTab="market" />,
  "system:quality": () => <SystemCenter initialTab="quality" />,
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const Page = PAGES[page] || UnknownPage;

  return (
    <TerminalLayout activePage={page} onNav={setPage}>
      <Page />
    </TerminalLayout>
  );
}
