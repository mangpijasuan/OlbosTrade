import React, { useState } from "react";
import "./index.css";
import TerminalLayout  from "./components/TerminalLayout";
import ChartWorkstation from "./pages/ChartWorkstation";
import Dashboard       from "./pages/Dashboard";
import TradeDesk       from "./pages/TradeDesk";
import RiskMonitor     from "./pages/RiskMonitor";
import Strategy        from "./pages/Strategy";
import Journal         from "./pages/Journal";
import Research        from "./pages/Research";
import Signals         from "./pages/Signals";
import Intel           from "./pages/Intel";
import Settings        from "./pages/Settings";

const PAGES: Record<string, React.ComponentType> = {
  chart:      ChartWorkstation,
  dashboard:  Dashboard,
  signals:    Signals,
  paper:      TradeDesk,
  risk:       RiskMonitor,
  strategy:   Strategy,
  journal:    Journal,
  research:   Research,
  intel:      Intel,
  settings:   Settings,
};

export default function App() {
  const [page, setPage] = useState("chart");
  const Page = PAGES[page] || Dashboard;

  return (
    <TerminalLayout activePage={page} onNav={setPage}>
      <Page />
    </TerminalLayout>
  );
}
