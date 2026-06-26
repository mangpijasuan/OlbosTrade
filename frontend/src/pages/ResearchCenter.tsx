/**
 * ResearchCenter — single "Research Lab" nav entry. Combines the strategy
 * promotion funnel + AI assistant (ResearchLab) with the market/regime/IV
 * intelligence page (Research), which previously sat under a confusingly-named
 * separate "Research" entry. Both components are reused unchanged.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import ResearchLab from "./ResearchLab";
import Research from "./Research";

const TABS = [
  { key: "lab", label: "Strategy Lab" },
  { key: "market", label: "Market & Regime" },
];

export default function ResearchCenter() {
  const [tab, setTab] = useState("lab");
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      {tab === "lab" ? <ResearchLab /> : <Research />}
    </div>
  );
}
