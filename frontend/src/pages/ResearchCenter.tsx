/**
 * ResearchCenter — single "Research Lab" nav entry. Folds the pre-trade
 * analysis surfaces behind tabs:
 *   - Strategy Lab      (strategy promotion funnel + AI assistant)
 *   - Market & Regime   (market/regime/IV intelligence)
 *   - Intel             (News & Catalyst Intelligence hub)
 * Chart Workstation lives under Markets → Chart instead (it's a price-action
 * viewing tool, not strategy research).
 * Each component is reused unchanged.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import ResearchLab from "./ResearchLab";
import Research from "./Research";
import Intel from "./Intel";
import ScenarioLab from "./research/ScenarioLab";
import MLModels from "./research/MLModels";

const TABS = [
  { key: "scenario", label: "Scenario Lab" },
  { key: "lab", label: "Strategy Research" },
  { key: "market", label: "Market & Regime" },
  { key: "intel", label: "Intel" },
  { key: "models", label: "Model Health" },
];

export default function ResearchCenter({ initialTab = "scenario" }: { initialTab?: string }) {
  const [tab, setTab] = useState(initialTab);
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} label="Research views" />
      <div id={`workspace-panel-${tab}`} role="tabpanel">
        {tab === "scenario" && <ScenarioLab />}
        {tab === "lab" && <ResearchLab />}
        {tab === "market" && <Research />}
        {tab === "intel" && <Intel />}
        {tab === "models" && <MLModels />}
      </div>
    </div>
  );
}
