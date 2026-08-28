/**
 * QuantLab — top-level page hub for Quant Research & Strategy Lab (Phase 1).
 *
 * Tabs:
 *   Strategy Builder  — compose and save deterministic strategies
 *   Strategy List     — view/manage saved strategies
 *   Backtest Lab      — run backtests and view results
 */

import React, { useState } from "react";
import TabBar from "../../components/TabBar";
import ErrorBoundary from "../../components/ErrorBoundary";
import StrategyBuilderPage from "./StrategyBuilder";
import StrategyList from "./StrategyList";
import BacktestLab from "./BacktestLab";

const TABS = [
  { key: "builder",  label: "Strategy Builder" },
  { key: "list",     label: "My Strategies" },
  { key: "backtest", label: "Backtest Lab" },
];

export default function QuantLab() {
  const [tab, setTab] = useState("builder");
  const [btStratId, setBtStratId] = useState<string | undefined>(undefined);

  const handleSelectForBacktest = (id: string) => {
    setBtStratId(id);
    setTab("backtest");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        <ErrorBoundary label={TABS.find(t => t.key === tab)?.label ?? "Quant Lab"}>
          {tab === "builder"  && <StrategyBuilderPage />}
          {tab === "list"     && <StrategyList onSelectForBacktest={handleSelectForBacktest} />}
          {tab === "backtest" && <BacktestLab preselectedStrategyId={btStratId} />}
        </ErrorBoundary>
      </div>
    </div>
  );
}
