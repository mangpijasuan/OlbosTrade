import React, { useState } from "react";
import "./index.css";
import TerminalLayout  from "./components/TerminalLayout";
import Dashboard       from "./pages/Dashboard";
import Backtest        from "./pages/Backtest";
import TradeDesk       from "./pages/TradeDesk";
import Journal         from "./pages/Journal";
import ModeAnalytics   from "./pages/ModeAnalytics";
import Symphony        from "./pages/Symphony";
// Consolidated hubs (each folds two former pages behind tabs)
import RiskCenter      from "./pages/RiskCenter";          // Risk Monitor + Guardrails
import SignalsCenter   from "./pages/SignalsCenter";       // Equity Signals + Strategy
import ResearchCenter  from "./pages/ResearchCenter";      // Research Lab + Market/Regime

const PAGES: Record<string, React.ComponentType> = {
  dashboard: Dashboard,
  paper:     TradeDesk,
  equity:    SignalsCenter,
  symphony:  Symphony,
  backtest:  Backtest,
  lab:       ResearchCenter,
  risk:      RiskCenter,
  journal:   Journal,
  analytics: ModeAnalytics,
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
