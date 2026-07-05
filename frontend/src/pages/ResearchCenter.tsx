/**
 * ResearchCenter — single "Research Lab" nav entry. Folds the pre-trade
 * analysis surfaces behind tabs:
 *   - Strategy Lab      (strategy promotion funnel + AI assistant)
 *   - Market & Regime   (market/regime/IV intelligence)
 *   - Chart             (Chart Workstation + Chart Intelligence panels)
 *   - Intel             (News & Catalyst Intelligence hub)
 * Each component is reused unchanged.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import ResearchLab from "./ResearchLab";
import Research from "./Research";
import ChartWorkstation from "./ChartWorkstation";
import Intel from "./Intel";

const TABS = [
  { key: "lab", label: "Strategy Lab" },
  { key: "market", label: "Market & Regime" },
  { key: "chart", label: "Chart" },
  { key: "intel", label: "Intel" },
];

export default function ResearchCenter() {
  const [tab, setTab] = useState("lab");
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      {tab === "lab" && <ResearchLab />}
      {tab === "market" && <Research />}
      {tab === "chart" && <ChartWorkstation />}
      {tab === "intel" && <Intel />}
    </div>
  );
}
