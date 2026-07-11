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

  // Grouped-nav aliases → existing pages (sub-items that already have a home).
  "trade:copilot":   TradeDesk,
  "trade:orders":    TradeDesk,
  "trade:positions": TradeDesk,
  "trade:logs":      TradeDesk,
  "strat:cards":     SignalsCenter,
  "options:cc":      CspScreener,
  "options:wheel":   CspScreener,
  "options:flow":    OptionsFlow,
  "risk:heat":       RiskCenter,
  "risk:exposure":   RiskCenter,
  "risk:drawdown":   RiskCenter,
  "data:broker":     Settings,
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
