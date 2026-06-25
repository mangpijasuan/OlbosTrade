import React, { useState } from "react";
import "./index.css";
import TerminalLayout  from "./components/TerminalLayout";
import Dashboard       from "./pages/Dashboard";
import Backtest        from "./pages/Backtest";
import TradeDesk       from "./pages/TradeDesk";
import RiskMonitor     from "./pages/RiskMonitor";
import Guardrails      from "./pages/Guardrails";
import Strategy        from "./pages/Strategy";
import Journal         from "./pages/Journal";
import Research        from "./pages/Research";
import ModeAnalytics   from "./pages/ModeAnalytics";
import EquitySignals   from "./pages/EquitySignals";
import Symphony        from "./pages/Symphony";
import ResearchLab     from "./pages/ResearchLab";

const PAGES: Record<string, React.ComponentType> = {
  dashboard:  Dashboard,
  symphony:   Symphony,
  lab:        ResearchLab,
  equity:     EquitySignals,
  backtest:   Backtest,
  paper:      TradeDesk,
  risk:       RiskMonitor,
  guardrails: Guardrails,
  strategy:   Strategy,
  journal:    Journal,
  research:   Research,
  analytics:  ModeAnalytics,
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
