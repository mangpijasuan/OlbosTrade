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
import CspScreener     from "./pages/CspScreener";          // Wheel & Income Lab
import ScanCenter      from "./pages/ScanCenter";           // Options + Equity EV scan engines
import Settings        from "./pages/Settings";             // Account, brokers, billing
import OptionsFlow     from "./pages/OptionsFlow";           // Options flow (grouped-nav sub-item)
import IncomeMatrix    from "./pages/IncomeMatrix";           // CSP + covered-call yield screener
import OptionsChain    from "./pages/options/OptionsChain";  // Live calls/puts for a symbol
import MLModels        from "./pages/research/MLModels";     // Signal-scorer model status
import StrategyBuilder from "./pages/strategies/StrategyBuilder"; // Configure + register a strategy experiment
import Alerts          from "./pages/strategies/Alerts";     // Smart Alert rules + notifications
// Markets module
import Heatmap         from "./pages/markets/Heatmap";
import Watchlists      from "./pages/markets/Watchlists";
import ChartWorkstation from "./pages/ChartWorkstation";     // Price-action / market-structure chart
import NewsCatalysts   from "./pages/markets/NewsCatalysts";
import MarketsCalendar from "./pages/markets/Calendar";
// Data & Integrations module
import BrokerGateway   from "./pages/data/BrokerGateway";
import MarketData      from "./pages/data/MarketData";
import DataQuality     from "./pages/data/DataQuality";

// Placeholder for sub-items in the grouped nav that don't have a page yet.
function ComingSoon() {
  return (
    <div style={{
      height: "100%", display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", gap: 8,
      color: "var(--ink-faint)", fontFamily: "var(--mono)",
    }}>
      <div style={{ fontSize: 13, letterSpacing: "0.12em", textTransform: "uppercase" }}>Coming soon</div>
      <div style={{ fontSize: 11, color: "var(--ink-dim)" }}>This module is on the roadmap.</div>
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
  csp:       CspScreener,
  scan:      ScanCenter,
  settings:  Settings,

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
  "options:cc":      () => <IncomeMatrix initialFilter="cc" />,
  "options:wheel":   CspScreener,
  "options:flow":    OptionsFlow,
  "risk:heat":       () => <RiskCenter initialTab="monitor" />,
  "risk:exposure":   () => <RiskCenter initialTab="monitor" />,
  "risk:drawdown":   () => <RiskCenter initialTab="monitor" />,
  "risk:rules":      () => <RiskCenter initialTab="guardrails" />,
  "lab:walkforward": () => <ResearchCenter initialTab="lab" />,
  "lab:ml":          MLModels,

  // Markets module
  "markets:heatmaps":   Heatmap,
  "markets:watchlists": Watchlists,
  "markets:chart":      ChartWorkstation,
  "markets:news":       NewsCatalysts,
  "markets:calendar":   MarketsCalendar,

  // Data & Integrations module
  "data:broker":  BrokerGateway,
  "data:market":  MarketData,
  "data:quality": DataQuality,
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const Page = PAGES[page] || ComingSoon;

  return (
    <TerminalLayout activePage={page} onNav={setPage}>
      <Page />
    </TerminalLayout>
  );
}
