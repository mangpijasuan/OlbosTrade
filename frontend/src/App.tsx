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
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const Page = PAGES[page] || Dashboard;

  return (
    <TerminalLayout activePage={page} onNav={setPage}>
      <Page />
    </TerminalLayout>
  );
}
