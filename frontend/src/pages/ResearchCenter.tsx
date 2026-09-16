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
import React from "react";
import TabBar from "../components/TabBar";
import ResearchLab from "./ResearchLab";
import Research from "./Research";
import Intel from "./Intel";
import ScenarioLab from "./research/ScenarioLab";
import MLModels from "./research/MLModels";
import { useTabRoute } from "../hooks/useTabRoute";

export const TABS = [
  { key: "scenario", label: "Scenario Lab" },
  { key: "lab", label: "Strategy Research" },
  { key: "market", label: "Market & Regime" },
  { key: "intel", label: "Intel" },
  { key: "models", label: "Model Health" },
];

/** Tab -> the page key that renders it, so a tab change shows up in the URL. */
/** Exported so the route table can be checked against the page registry — see src/hooks/__tests__/tabRouteTable.test.tsx. */
/** The tab the page opens on when the URL names it without one. */
export const DEFAULT_TAB = "scenario";

export const TAB_PAGE_KEYS = {
  scenario: "lab:scenario",
  lab: "lab:strategy",
  market: "lab:market",
  intel: "lab:intel",
  models: "lab:models",
} as const;

export default function ResearchCenter({ initialTab = DEFAULT_TAB }: { initialTab?: string }) {
  const [tab, setTab] = useTabRoute(initialTab, TAB_PAGE_KEYS);
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
