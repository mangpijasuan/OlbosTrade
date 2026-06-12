import React, { useState } from "react";
import "./index.css";
import TerminalLayout from "./components/TerminalLayout";
import Dashboard     from "./pages/Dashboard";
import Backtest      from "./pages/Backtest";
import PaperTrade    from "./pages/PaperTrade";
import RiskMonitor   from "./pages/RiskMonitor";
import Guardrails    from "./pages/Guardrails";
import Strategy      from "./pages/Strategy";
import Journal       from "./pages/Journal";
import Research      from "./pages/Research";
import ModeAnalytics from "./pages/ModeAnalytics";

const PAGES: Record<string, React.ComponentType> = {
  dashboard:  Dashboard,
  backtest:   Backtest,
  paper:      PaperTrade,
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
