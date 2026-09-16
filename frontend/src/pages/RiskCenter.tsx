/**
 * RiskCenter — single "Risk" nav entry combining the Risk Monitor and Guardrails
 * pages (both were built on the same useRisk hook). Tabs switch between them; the
 * underlying page components are reused unchanged.
 */
import React from "react";
import TabBar from "../components/TabBar";
import RiskMonitor from "./RiskMonitor";
import Guardrails from "./Guardrails";
import { useTabRoute } from "../hooks/useTabRoute";

export const TABS = [
  { key: "monitor", label: "Risk Monitor" },
  { key: "guardrails", label: "Guardrails" },
];

/** Tab -> the page key that renders it, so a tab change shows up in the URL. */
/** Exported so the route table can be checked against the page registry — see src/hooks/__tests__/tabRouteTable.test.tsx. */
/** The tab the page opens on when the URL names it without one. */
export const DEFAULT_TAB = "monitor";

export const TAB_PAGE_KEYS = {
  monitor: "risk:heat",
  guardrails: "risk:rules",
} as const;

export default function RiskCenter({ initialTab = DEFAULT_TAB }: { initialTab?: string }) {
  const [tab, setTab] = useTabRoute(initialTab, TAB_PAGE_KEYS);
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      {tab === "monitor" ? <RiskMonitor /> : <Guardrails />}
    </div>
  );
}
